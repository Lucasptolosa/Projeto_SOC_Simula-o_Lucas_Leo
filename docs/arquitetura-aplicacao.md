# Arquitetura dos componentes

O Mini SOC segue o [ADR-001](adr/01-arquitetura-inicial.md): uma aplicação
FastAPI, organizada em módulos, com PostgreSQL compartilhado. Os contratos
funcionais e a matriz de permissões estão na [especificação](../spec.md).
Instalação, configuração, migrations e execução estão no [README](../README.md).

## Camadas e transações

- `router.py`: contrato HTTP, dependências, códigos de resposta e confirmação
  da transação de escrita.
- `schemas.py`: validação Pydantic e projeções públicas de entrada e saída.
- `service.py`: coordenação das regras, autorização contextual e auditoria.
- `repository.py`: consultas, ordenação, locks e operações SQLAlchemy.
- `models.py`: mapeamento ORM e constraints de integridade.

Esses arquivos estão em `backend/app/` dentro dos módulos correspondentes.
Nem todo módulo precisa das cinco camadas: as regras puras de domínio não
dependem de HTTP ou de persistência.

[Base](../backend/app/db/base.py), [Engine e fábrica de sessões](../backend/app/db/session.py)
são compartilhados. `get_session` fornece a sessão por requisição e a fecha ao
terminar; operações não confirmadas são revertidas. Serviços e repositórios
não confirmam isoladamente partes de uma operação de negócio. A conexão usa
READ COMMITTED, `pool_pre_ping`, timeout e ocultação de parâmetros SQL.

As [migrations](../backend/migrations/versions) formam uma cadeia única:
Users → sessões → Audit Logs → Assets → Logs. Os modelos são carregados pelo
[ambiente Alembic](../backend/migrations/env.py) para compor a metadata comum.
Papéis, estados e tipos são textos com constraints, sem enums nativos do
PostgreSQL. Regras de domínio sem ORM não criam tabelas.

## Identidade, sessões e autorização

[Autenticação](../backend/app/auth/service.py) verifica hashes Argon2id e cria
sessões opacas. O cookie `mini_soc_session` contém um token aleatório de
256 bits; o banco armazena seu hash SHA-256, usuário, expiração e revogação.
O token CSRF é derivado por HMAC e comparado em tempo constante.

[get_current_user](../backend/app/auth/dependencies.py) confere a sessão,
expiração, revogação e estado ACTIVE do User em cada acesso. Escritas exigem
origem correspondente à configuração e `X-CSRF-Token`. Login exige Origin.
[require_roles](../backend/app/auth/authorization.py) aplica permissões
explícitas no servidor; ADMIN não herda o papel ANALYST.

Login e `GET /auth/me` retornam `id`, `username`, `role`, `status` e
`csrf_token`. O cliente mantém o cookie no mecanismo normal do navegador e
envia `csrf_token` como `X-CSRF-Token` nas escritas, incluindo logout.
Credenciais inválidas ou User inativo produzem a mesma resposta 401.
Logout bem-sucedido retorna 204 e remove o cookie.

O papel atual é lido do banco. Um novo login revoga a sessão apresentada no
cookie, sem encerrar todas as sessões da conta. Logout revoga a sessão atual;
desativação de User revoga todas as suas sessões. A validade é absoluta, sem
renovação automática. Limpeza periódica das sessões não é fornecida pela API.

## Users, Assets e concorrência

[Users](../backend/app/users/service.py) admite cadastro, alteração de nome ou
papel de outra conta e desativação. Nome é único no banco. Não há exclusão
física, redefinição de senha ou reativação. Alteração da própria conta é
recusada; o último ADMIN ativo é protegido contra desativação e mudança de papel.

As escritas administrativas de Users usam lock transacional compartilhado
pelo protocolo de aplicação, com timeout de cinco segundos. O autor é
revalidado e o alvo é bloqueado antes da alteração. O login também bloqueia a
linha do User, serializando sua criação de sessão com a desativação da conta.
Essas garantias dependem da utilização dos serviços; não constituem proteção
contra escrita administrativa direta no banco.

[Assets](../backend/app/assets/service.py) reutiliza a serialização e a
revalidação do autor para criar, alterar nome/tipo e desativar ativos. Não há
reativação ou exclusão. Alteração sem efeito e desativação de Asset já inativo
não geram novo registro de auditoria. A API não oferece listagem de Assets.

## Auditoria e consultas administrativas

[AuditLog](../backend/app/audit/models.py) contém UUID, autor, ação, tipo e
identificador textual da entidade, instante com fuso e papéis anterior/novo
quando aplicáveis. A FK do autor impede exclusão que invalide o histórico.
Os dois campos de papel ficam simultaneamente nulos ou contêm ADMIN/ANALYST.
Eles não representam mudanças de Status de Alerts ou Incidents.

[append_audit](../backend/app/audit/service.py) adiciona o registro à mesma
sessão da alteração de User ou Asset, sem commit próprio. Falha em qualquer
gravação reverte a operação completa. Alteração conjunta de nome e papel gera
um registro. Consultas não produzem auditoria de alteração.

`GET /users` e `GET /audit-logs` são exclusivos de ADMIN. A paginação usa
`page` de 1 a 10.000 e `page_size` de 1 a 100, com padrões 1 e 20. Parâmetros
desconhecidos ou inválidos são rejeitados. Users aceita filtros de papel e
estado e ordena por `username ASC, id ASC`; auditoria usa
`occurred_at DESC, id DESC`. Respostas projetam apenas campos públicos.

Contagem e itens são consultas separadas em READ COMMITTED; mudanças
concorrentes podem alterar o conjunto entre consultas ou páginas. Não há
snapshot de navegação. Audit Logs não possuem rotas de alteração ou exclusão;
essa proteção da API não equivale a uma política de imutabilidade para
administradores do PostgreSQL.

## Importação de Logs

[Schemas](../backend/app/logs/schemas.py), [serviço](../backend/app/logs/service.py)
e [repositório](../backend/app/logs/repository.py) implementam os contratos da
seção 3.1.1 da spec. Pydantic rejeita NUL, UTF-8 inválido e campos desconhecidos
por item; textos válidos são preservados. O limite de `event_id` é medido em
bytes, não em caracteres: 512 caracteres de dois bytes ou 256 de quatro bytes
atingem 1.024 bytes.

A chave primária textual garante unicidade. A constraint
`ck_logs_event_id_bytes`, no [modelo](../backend/app/logs/models.py) e na
[migration 0005](../backend/migrations/versions/0005_create_logs.py), usa
`octet_length(convert_to(event_id, 'UTF8'))`. Esse limite evita que a API
prometa identificadores arbitrariamente grandes para um índice B-tree.

A consulta de Asset usa `FOR KEY SHARE`; Asset INACTIVE pode receber eventos
históricos. O insert usa `ON CONFLICT DO NOTHING` com retorno para distinguir
aceitação de duplicata mesmo entre conexões concorrentes. Não há substituição
do Log original. Rejeições previstas preservam os demais registros válidos;
falha operacional reverte o lote inteiro. A resposta de sucesso só é enviada
após commit.

Importação não consulta regras nem cria Alerts. O modelo ORM `LogRecord` e o
objeto de domínio `Log` do Detection Engine têm responsabilidades distintas;
o fluxo persistente de detecção precisa coordenar essa conversão, ordenação,
continuidade e gravação de resultados conforme RF07/RF08 e seção 8.2.
Uma rejeição do motor por ordem temporal não altera o contrato de ingestão.

Para validar os contratos de ingestão, a partir de `backend/`, com o banco de
testes configurado exclusivamente como `mini_soc_test`:

```powershell
python -m pytest tests/test_log_validation.py tests/test_logs.py tests/test_users.py -q
```

Os testes cobrem limites em bytes, multibyte, NUL, UTF-8 inválido, lotes mistos,
constraint real, unicidade entre conexões, commit, rollback e autorização.

## Detection Engine e domínio

O [Detection Engine](../backend/app/detection_engine.py) é Python em memória,
com `Log`, `DetectionRule`, `Alert` e `ProcessingResult`. Ordena cada lote por
data/hora e identificador, acompanha o último instante por Asset/username e
deduplica eventos e sequências. Instâncias e seu estado precisam ser
controlados pelo serviço consumidor; não há cursor durável ou garantia de
idempotência entre processos.

DR01, DR02 e DR03 mantêm os parâmetros da spec. O histórico de falhas continua
sendo acompanhado com regras inativas. AUTH_SUCCESS encerra a sequência da
DR02 mesmo inativa, mas não encerra por si só a sequência da DR01. Registro
interno de avaliadores não permite cadastrar novos tipos pela aplicação.
O [ADR-002](adr/02-extensao-detection-rules.md) descreve esse mecanismo e mantém
seu estado formal de proposta.

[Incidents](regras-transicao-incidentes.md) e
[Investigations](regras-investigacoes.md) são validadores independentes de
HTTP, ORM e do motor. Seus contratos não criam entidades, rotas ou transações.
A integração persistente deve preservar autoria, horário, evidências,
concorrência e auditoria previstos na spec.

## Interface web e erros

[Rotas web](../backend/app/web/router.py) fornecem login, área autenticada,
gestão de Users e consulta de auditoria. Páginas protegidas redirecionam
sessões inválidas ao login; APIs respondem 401. Papel incompatível recebe 403
antes da construção da página. Templates não recebem o ORM User nem tokens
de sessão; a identidade é consultada em `/auth/me`.

Os [scripts locais](../backend/app/web/static) mantêm CSRF somente em memória,
usam `textContent` para dados e não persistem tokens em localStorage ou URLs.
Jinja mantém escape de HTML. A aplicação define CSP restritiva, proteção
contra enquadramento, `nosniff`, política de referência e ausência de cache
para conteúdo protegido. Não há scripts externos ou build de front-end.

A gestão de Users confirma senhas no cliente e desativação em diálogo, limpa
campos de senha e bloqueia ações repetidas enquanto a escrita está em curso.
Uma falha de rede pode ocorrer após o commit; o cliente não repete a escrita
automaticamente. O estado deve ser consultado antes de nova tentativa.

[Tratamento de erros](../backend/app/core/errors.py) devolve erro genérico
para falha interna e validações de auth, Users, consultas de auditoria e Logs.
Rejeições de importação não ecoam os valores recebidos. A proteção do logger
da aplicação não abrange o processo PostgreSQL; configuração, verificação e
limitações desse logging estão no README.
