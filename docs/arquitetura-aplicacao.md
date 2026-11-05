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
Users → sessões → Audit Logs → Assets → Logs → detecção → Investigations → Incidents.
A revisão `0006_detection_persistence` acrescenta catálogo, estado, Alerts e
evidências. Os modelos são carregados pelo
[ambiente Alembic](../backend/migrations/env.py) para compor a metadata comum.
Papéis, estados e tipos são textos com constraints, sem enums nativos do
PostgreSQL. Regras de domínio sem ORM não criam tabelas.

A revisão `0007_create_investigations` cria as investigações e observações e
estende Audit Logs com campos próprios de Status, preservando as revisões e
os registros existentes.

A revisão `0008_create_incidents` acrescenta Incidents com vínculo único ao
Alert, responsável, Severity herdada, Status e instante de abertura. Não altera
as revisões anteriores ou as entidades de Alert/Investigation.

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

`old_status/new_status` registram mudanças de Status em um par próprio,
simultaneamente nulo ou preenchido. Constraints impedem pares incompletos,
valores vazios ou mistura com mudança de papel no mesmo registro.

[append_audit](../backend/app/audit/service.py) adiciona o registro à mesma
sessão da alteração de User, Asset ou descarte de Alert, sem commit próprio. Falha em qualquer
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

Após inserir os Logs novos, o serviço chama a integração de detecção. O modelo
ORM `LogRecord` e o objeto de domínio `Log` têm responsabilidades distintas;
o adaptador converte os registros inseridos para avaliação, sem duplicar a
entidade persistente. Itens inválidos ou duplicados não entram no motor.
Uma rejeição temporal de detecção preserva o Log válido e não altera as
contagens de ingestão. O bloco `detection` da resposta distingue avaliação,
rejeições por posição original e quantidade de Alerts criados conforme a
seção 3.1.2 da spec.

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
deduplica eventos e sequências. O núcleo não acessa banco ou HTTP. A integração
persistente restaura uma instância por transação para conservar o estado
confirmado entre lotes e reinícios, sem compartilhar uma instância global.

DR01, DR02 e DR03 mantêm os parâmetros da spec. O histórico de falhas continua
sendo acompanhado com regras inativas. AUTH_SUCCESS encerra a sequência da
DR02 mesmo inativa, mas não encerra por si só a sequência da DR01. Registro
interno de avaliadores não permite cadastrar novos tipos pela aplicação.
O [ADR-002](adr/02-extensao-detection-rules.md) descreve esse mecanismo e mantém
seu estado formal de proposta.

### Catálogo, estado e Alerts

O módulo `backend/app/detection/` contém:

- [models.py](../backend/app/detection/models.py): `DetectionRuleRecord`,
  `DetectionState`, `AlertRecord` e `AlertLog`, na Base compartilhada.
- [state.py](../backend/app/detection/state.py): serialização JSONB versionada
  do histórico, deduplicação, último instante por conta/Asset e contador interno.
- [repository.py](../backend/app/detection/repository.py): locks, catálogo,
  gravação dos Alerts/evidências e atualização do estado.
- [service.py](../backend/app/detection/service.py): adaptação de Logs, avaliação,
  persistência de resultados e resumo público de detecção.

A linha `detection_state` de identificador 1 é bloqueada com `FOR UPDATE` antes
da inserção de Logs. A ordem de locks é autor, estado, Assets e catálogo ordenado
por identificador. Cada lote restaura o último estado confirmado em READ
COMMITTED e lê o catálogo persistido. Estado ausente, versão inválida ou catálogo
incompleto abortam a operação; não há reset silencioso.

O lote que obtém primeiro o lock define a precedência entre requisições. Dentro
do lote, o motor ordena `occurred_at` e `event_id`; a avaliação de eventos fora
de ordem compara com o estado confirmado antes desse lote. Logs rejeitados
somente para detecção não alteram sequências nem produzem Alerts.

`AlertRecord` recebe UUID, regra, Asset, conta monitorada, evento acionador,
Severity, Status NEW e `created_at` igual ao instante desse evento. IDs internos
do motor não identificam Alerts persistidos. `AlertLog` conserva a ordem das
evidências. FKs RESTRICT preservam os vínculos e a unicidade de regra/evento
acionador complementa a deduplicação temporal de DR01/DR02.

O router confirma uma única transação com Logs, Alerts, evidências e novo estado.
Falhas de avaliação, gravação ou commit revertem todas essas mudanças. O estado
restaurado não é reutilizado globalmente após rollback. A migration inicializa
DR01-DR03 ACTIVE com Severity fixa e estado vazio; não avalia Logs existentes.

Essa coordenação reduz paralelismo, e o histórico serializado cresce com os
eventos. Alterações nos campos internos do motor exigem compatibilidade do
formato e testes de recuperação. O [ADR-003](adr/03-estado-transacional-detection-engine.md)
detalha a proposta e permanece pendente de revisão arquitetural. A administração
de regras e a consulta de Alerts são descritas abaixo; a geração não
autoriza ADMIN a consultá-los. RNF03 completo e RNF06 exigem verificações próprias.

### Administração de regras

[router.py](../backend/app/detection/router.py) recebe somente status na rota
`PATCH /detection-rules/{rule_id}`, usando require_roles(ADMIN), Origin, CSRF e
get_session existentes. [schemas.py](../backend/app/detection/schemas.py) rejeita
campos extras e estados diferentes de ACTIVE/INACTIVE e projeta id/status/severity.
O contrato HTTP, inclusive repetições sem efeito, está na seção 3.3 da spec.

O serviço revalida o autor com bloqueio de sua linha, adquire o bloqueio do
estado singleton existente e usa rule_by_id com FOR UPDATE/populate_existing.
Essa ordem é compatível com a importação, que obtém o mesmo bloqueio antes de
inserir Logs e ler o catálogo. Alteração e lote concorrentes observam o estado
confirmado segundo a precedência desse bloqueio, sem mutex local por processo.

Somente uma mudança efetiva chama append_audit com entidade DETECTION_RULE e
ação DETECTION_RULE_ACTIVATED/DEACTIVATED. Regra e Audit Log usam a mesma sessão;
o router valida a projeção e faz o único commit. Uma repetição não escreve outra
auditoria. Ausência de catálogo ou estado não é reparada automaticamente.
Não há nova migration, limpeza de histórico ou alteração dos algoritmos do motor.

Os núcleos de [Incidents](regras-transicao-incidentes.md) e
[Investigations](regras-investigacoes.md) continuam independentes de HTTP,
ORM e do motor. A camada de aplicação de Investigations reutiliza os
validadores de início e falso positivo sobre o mesmo `AlertRecord`.

Investigation possui relação única com Alert e registra autor/instante de início.
Cada observação possui autor, conteúdo e instante próprios. Descarte preserva
justificativa, autor e instante e grava um Audit Log com Status anterior/novo.
As escritas bloqueiam o User para revalidar papel/estado e depois o Alert para
serializar decisões; o router confirma ou reverte toda a operação. Não há
restrição de autoria exclusiva ao analista inicial.

O serviço de [Incidents](../backend/app/incidents/service.py) reutiliza esse
contexto e `validate_escalation_eligibility`, adicionando o Incident OPEN,
copiando a Severity e alterando o Alert para ESCALATED. `ALERT_ESCALATED` registra
autor, Alert, Status anterior/novo e o mesmo instante da abertura. Unicidade
por Alert e o lock compartilhado impedem duplicação e decisões concorrentes
com False Positive. Incident, Alert e auditoria são confirmados ou revertidos
juntos pela fronteira transacional existente. Os validadores de tratamento
permanecem separados, sem rotas de execução dessas transições.

## Consulta de Alerts

O módulo [alerts](../backend/app/alerts/router.py) oferece GET /alerts e
GET /alerts/{id} somente a ANALYST ativo, com require_roles/get_session existentes.
O serviço revalida o autor com current_user/populate_existing. Não solicita locks
de escrita nem confirma transações. Sessões e autorização preservam seus controles.

[Schemas](../backend/app/alerts/schemas.py) reutilizam PaginationQuery e Page,
validam filtros/UUIDs/períodos e projetam campos públicos. O
[repositório](../backend/app/alerts/repository.py) reutiliza AlertRecord, AlertLog
e LogRecord, sem novo ORM ou migration. Filtros são predicados SQL parametrizados,
aplicados tanto à contagem quanto aos itens. A ordenação é created_at DESC/id ASC;
evidências usam AlertLog.position, sem joins que multipliquem a lista de Alerts.

O detalhe consulta somente os Logs vinculados ao Alert solicitado. Dados e
contagens são leituras separadas em READ COMMITTED; não há snapshot entre páginas
ou bloqueio do motor. A consulta não gera Alerts, altera Status ou grava auditoria.
Os contratos HTTP estão na seção 3.4 da spec; validação funcional não comprova RNF05.

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
