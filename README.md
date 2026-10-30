# Mini SOC

Sistema acadêmico de monitoramento de segurança, desenvolvido para receber logs simulados, aplicar regras de detecção, gerar alertas e permitir a investigação e o tratamento de incidentes.

Projeto de Modelagem de Sistemas desenvolvido por Lucas e Leonardo.
O escopo é definido em [spec.md](spec.md) e a arquitetura no
[ADR-001](docs/adr/01-arquitetura-inicial.md).

## Tecnologias

- Python 3.14 (ambiente validado com Python 3.14.8)
- FastAPI
- PostgreSQL
- SQLAlchemy
- Psycopg
- Alembic
- pytest

## Pré-requisitos

- Python 3.14
- PostgreSQL
- Git

## Instalação

Clone o repositório e acesse sua pasta:

```powershell
git clone https://github.com/Lucasptolosa/Projeto_SOC_Simula-o_Lucas_Leo.git
cd Projeto_SOC_Simula-o_Lucas_Leo
```

Na raiz do repositório, crie e ative o ambiente virtual:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Instale as dependências:

```powershell
python -m pip install -r backend/requirements-dev.txt
```

Para instalar somente as dependências de execução, utilize
`python -m pip install -r backend/requirements.txt`.

## Configuração do PostgreSQL

No PostgreSQL, crie:

- Uma Role chamada `mini_soc_app`, com permissão de login, senha própria e sem privilégios de superusuário.
- Um banco chamado `mini_soc_dev`, com `mini_soc_app` como proprietário.
- Um banco chamado `mini_soc_test`, com `mini_soc_app` como proprietário.

O banco `mini_soc_dev` será utilizado para desenvolvimento, enquanto `mini_soc_test` será utilizado nos testes automatizados.

Em uma sessão administrativa do `psql`, execute uma única vez, em um servidor
local onde esses nomes ainda não existam:

```sql
CREATE ROLE mini_soc_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
\password mini_soc_app
CREATE DATABASE mini_soc_dev OWNER mini_soc_app;
CREATE DATABASE mini_soc_test OWNER mini_soc_app;
```

O comando `\password` solicita a senha interativamente. Se os recursos já
existirem, confirme sua configuração; não é necessário recriá-los.

## Variáveis de ambiente

Dentro de `backend/`, crie os arquivos `.env` e `.env.test`, utilizando `.env.example` como referência.

A partir da raiz, copie o exemplo apenas se os arquivos ainda não existirem:

```powershell
Copy-Item backend/.env.example backend/.env
Copy-Item backend/.env.example backend/.env.test
```

### Desenvolvimento (`.env`)

```dotenv
DB_HOST=localhost
DB_PORT=5432
DB_NAME=mini_soc_dev
DB_USER=mini_soc_app
DB_PASSWORD=SENHA_LOCAL
```

### Testes (`.env.test`)

```dotenv
DB_HOST=localhost
DB_PORT=5432
DB_NAME=mini_soc_test
DB_USER=mini_soc_app
DB_PASSWORD=SENHA_LOCAL
```

Substitua `SENHA_LOCAL` pela senha da Role criada no PostgreSQL.

**Não versione arquivos `.env`, `.env.test` ou credenciais reais.**

As variáveis do processo têm precedência sobre os arquivos dotenv. Antes dos
testes, remova ou ajuste variáveis `DB_*` exportadas no terminal que apontem
para outro ambiente. Os testes recusam um `DB_NAME` diferente de
`mini_soc_test` e confirmam o banco real antes de criar tabelas temporárias.
A conexão limita a espera a 5 segundos por tentativa de conexão ao servidor.

## Executar a aplicação

Acesse a pasta `backend`:

```powershell
cd backend
```

Inicie o servidor:

```powershell
python -m uvicorn app.main:app --reload
```

Documentação interativa da API:

http://127.0.0.1:8000/docs

O endpoint `GET /health` retorna HTTP 200 e `{"status":"ok"}`. Ele verifica
somente a API, sem testar a disponibilidade do PostgreSQL.

## Testes automatizados

Dentro da pasta `backend`, execute:

```powershell
python -m pytest -q
```

Para executar os testes e medir a cobertura:

```powershell
python -m pytest --cov=app --cov-report=term-missing -q
```

Os testes seguem o padrão **AAA (Arrange, Act, Assert)**.

Metas de cobertura:

- Cobertura geral: pelo menos 70%.
- Detection Rules e transições de Incident: pelo menos 80%.

Os testes de integração utilizam o banco `mini_soc_test`.
Eles exigem PostgreSQL disponível e o arquivo `backend/.env.test` configurado.
Os testes transacionais usam tabelas `TEMPORARY` no schema `pg_temp`, exclusivas
da conexão e removidas automaticamente pelo PostgreSQL ao desconectá-la.
Os testes de Users criam um schema com nome aleatório em `mini_soc_test`,
aplicam a migration nesse schema dentro de uma transação externa e isolam
cada sessão com savepoints. Ao terminar, revertem a transação externa,
incluindo o schema criado. Não executam `DROP`, `DELETE` ou alterações em
tabelas preexistentes. Nunca apontam para `mini_soc_dev`.

As sessões são disponibilizadas por `get_session()`. Cada serviço deve
confirmar explicitamente sua transação com `session.commit()` ou usar
`with session.begin():`. O encerramento da dependência fecha a sessão e
desfaz qualquer gravação ainda não confirmada, inclusive após uma exceção.

## Migrations

O Alembic é utilizado para versionar alterações na estrutura do banco de dados.

Dentro de `backend`, verifique a revisão atual:

```powershell
python -m alembic current
```

Para aplicar as migrations existentes:

```powershell
python -m alembic upgrade head
```

Os arquivos de migrations ficam em `backend/migrations/versions/`.

A revisão inicial `0001_create_users` cria somente a tabela `users`, com
chave UUID, username único, papel, estado e hash de senha. Revise o arquivo
antes de aplicar em seu ambiente. Ela não altera tabelas de outros módulos
nem cria contas. Se já existir uma tabela `users` não gerenciada pelo
Alembic, interrompa a instalação e concilie o esquema; não recrie a tabela.

O `target_metadata` aponta para a Base declarativa compartilhada e registra
o modelo User, permitindo comparação do esquema e autogenerate. Não há
Enum nativo do PostgreSQL: papel e estado usam texto com CHECKs nomeados,
evitando tipos compartilhados ou objetos adicionais nesta migration.

O downgrade dessa revisão é bloqueado para impedir a exclusão de Users.
Uma eventual reversão exige planejamento específico com preservação dos
dados. Migrations offline ainda não são suportadas. A URL de conexão é
construída a partir de `Settings`; o valor genérico de `sqlalchemy.url` em
`alembic.ini` não é utilizado.

## Users e Administrator inicial — Issue #14

O modelo `app/users/models.py` persiste somente `id`, `username`, `role`,
`status` e `password_hash`. UUIDs são gerados na aplicação. Username é
obrigatório, não pode conter apenas espaços e é preservado exatamente como
informado, sem conversão de maiúsculas/minúsculas. A unicidade é aplicada
pelo banco; `a` e `A` são nomes distintos. Não foi criada uma política nova
de comprimento de senha ou username ausente da spec.

Os papéis permitidos são `ADMIN` e `ANALYST`; os estados são `ACTIVE` e
`INACTIVE`, com padrão `ACTIVE`. As restrições de unicidade, nulidade,
papel, estado e formato de hash também existem no banco, além da validação
ORM. O CHECK de hash confere formato; ele não comprova que o hash foi
produzido a partir de uma senha. O procedimento usa exclusivamente a função
de hash da aplicação, nunca aceita um hash fornecido pelo operador.

Após configurar o banco e aplicar a migration, execute em `backend/`, num
terminal interativo com o ambiente virtual ativo:

```powershell
python -m app.users.create_admin
```

O comando solicita o nome do Administrator e a senha duas vezes, sem eco.
Não aceita argumentos, senha por pipe ou credenciais fixas. Use uma senha
própria e mantenha-a fora de arquivos, histórico do terminal e Git.
Senha vazia ou composta somente de espaços é recusada; os demais caracteres
da senha são preservados, sem normalização ou truncamento.

O procedimento cria um `ADMIN ACTIVE` somente se não existir qualquer User.
A criação inteira ocorre numa transação. Um lock de tabela serializa
tentativas concorrentes e impede inserções concorrentes durante a checagem.
Se já houver conta, o comando termina com erro e não redefine senha, papel
ou estado. Não use o bootstrap como ferramenta de recuperação de contas.
O acesso ao terminal e às credenciais do PostgreSQL deve ser restrito ao
operador responsável pela instalação.

O hash usa Argon2id v19 com salt aleatório de 16 bytes por geração, saída de
32 bytes, memória de 65.536 KiB, três iterações e paralelismo quatro. Esses
parâmetros correspondem ao perfil de menor memória do RFC 9106 na
[documentação do argon2-cffi](https://argon2-cffi.readthedocs.io/en/stable/parameters.html).
O salt e os parâmetros fazem parte do hash codificado; não há coluna de
senha original. Parâmetros SQL são ocultados nas representações de erros
do Engine, e o comando mostra mensagens genéricas, sem senha ou hash.

Rastreabilidade desta entrega:

- **RNF01:** Argon2id, salt individual e armazenamento exclusivo do hash.
- **RF19.1 (parcial):** estrutura persistente, unicidade, papel válido e
  estado inicial; o endpoint de cadastro administrativo ainda não existe.
- **Seção 2 / CE01:** procedimento documentado de Administrator inicial.
- **RNF03 (parcial):** leitura e integridade de Users verificadas no
  PostgreSQL. A suíte usa savepoints numa transação externa revertida;
  não demonstra recuperação após reinício do servidor ou da aplicação.
- **RNF09 (apoio):** ocultação de parâmetros e erros do bootstrap; o
  tratamento completo de logs técnicos do servidor continua pendente.

Essa entrega de Users não adicionou login, autorização, cadastro público, endpoints
administrativos, auditoria administrativa nem regra do último ADMIN.
Esses comportamentos permanecem nas respectivas Issues. A instalação local
real não cria contas automaticamente durante migrations ou testes.

## Autenticação e sessões — Issue #16

O módulo `app/auth` reutiliza User e adiciona sessões opacas persistidas no
servidor. A migration `0002_create_auth_sessions` depende de
`0001_create_users` e cria somente `auth_sessions`, com FK para Users,
hash único do token, datas UTC de criação/expiração e revogação opcional.
Revise ambas antes de executar `python -m alembic upgrade head`.
O downgrade destrutivo permanece bloqueado. As migrations não criam contas.

Configure a origem exata do navegador em `.env`, incluindo esquema e porta:

```dotenv
AUTH_ORIGIN=https://seu-host
AUTH_COOKIE_SECURE=true
AUTH_SESSION_SECONDS=28800
```

O padrão é `https://localhost`, cookie Secure e validade absoluta de oito
horas. A duração aceita valores de 1 a 86.400 segundos. Para desenvolvimento
local via HTTP, configure explicitamente:

```dotenv
AUTH_ORIGIN=http://127.0.0.1:8000
AUTH_COOKIE_SECURE=false
```

Cookie sem Secure só é aceito em HTTP com host `localhost`, `127.0.0.1`
ou `::1`. Não use essa exceção fora de loopback. A origem configurada é
fixa, sem caminho, usuário, senha, query ou fragmento; não é inferida do
header Host ou de headers de proxy. Não há CORS liberado nesta entrega.

| Endpoint | Comportamento |
|---|---|
| `POST /auth/login` | JSON com `username` e `password`, mais header `Origin` correspondente à configuração. Retorna dados públicos e `csrf_token`; envia o token de sessão somente por cookie. |
| `GET /auth/me` | Cookie válido retorna `id`, `username`, `role`, `status` e `csrf_token`. Nunca retorna hash de senha ou token de sessão. |
| `POST /auth/logout` | Exige cookie, `Origin` válido e `X-CSRF-Token`. Revoga a sessão no servidor, remove o cookie e retorna 204. |

O cookie `mini_soc_session` é HttpOnly, SameSite=Strict, Path=/, sem Domain
e Secure por padrão. Possui Max-Age igual à duração configurada. O servidor
gera um token aleatório de 256 bits e persiste somente seu SHA-256; não há
JWT ou token em URL/localStorage. SHA-256 é usado para tokens de alta
entropia, enquanto as senhas continuam com Argon2id.

Um novo login revoga a sessão apresentada anteriormente e gera outro token,
reduzindo risco de fixação de sessão. Ele não encerra outras sessões do
mesmo usuário. A expiração é conferida no servidor, inclusive no instante
exato do vencimento, independentemente da validade do cookie no navegador.
Logout revoga antes de remover o cookie, impedindo replay. Registros de
sessões expiradas ou revogadas são preservados; limpeza automática não foi
incluída nesta entrega.

### CSRF e uso pelo cliente

Login aceita apenas JSON e exige Origin válido, recusando origens ausentes,
`null` ou diferentes. Isso protege o login contra requisições cross-site
do navegador sem criar uma sessão prévia. Após o login, obtenha o
`csrf_token` retornado e envie-o em `X-CSRF-Token` nas operações autenticadas
de escrita. Após recarregar a página, recupere-o por `GET /auth/me`.

O token CSRF é HMAC-SHA-256 derivado do segredo da sessão com um rótulo
fixo; não é o identificador da sessão e não é persistido em claro. A
comparação usa tempo constante. A política de mesma origem do navegador
impede que outra origem leia as respostas, e não há configuração CORS
permitindo essa leitura. SameSite é uma camada adicional, sem substituir
a validação de Origin ou do token. Essas escolhas seguem as orientações
de [CSRF](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
e [sessões](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
da OWASP.

A dependência `get_current_user` recupera User pelo cookie, valida
expiração/revogação e consulta seu estado ACTIVE em cada acesso. Nas
operações diferentes de GET/HEAD/OPTIONS, exige também Origin e CSRF.
Reutilize-a nos próximos endpoints protegidos. Ela autentica, mas ainda
não aplica sozinha a matriz de permissões por papéis. Para isso, use
`require_roles`, descrito na seção de autorização abaixo.

Usuário inexistente, senha incorreta e User INACTIVE recebem o mesmo 401:
`Credenciais inválidas.`. A verificação Argon2id também é realizada com um
hash fictício quando o username não existe, reduzindo diferenças temporais.
Sessão ausente, inválida, expirada, revogada ou de usuário inativo recebe
401 genérico. Uma resposta 403 de CSRF não revoga uma sessão válida.

Respostas de autenticação usam `Cache-Control: no-store`. Erros de validação
não devolvem o corpo ou senha enviados. Falhas não tratadas retornam 500
genérico e registram timestamp UTC, rota estática e categoria do erro, sem
corpo, cookies, tokens, hashes, senha ou traceback. Parâmetros SQL permanecem
ocultos. Testes cobrem também a ausência de segredos nessas mensagens.

### Limites e rastreabilidade

- RF01/RF02: login e negação genérica de credenciais inválidas/inativas.
- RNF01: verificação Argon2id, preservando o armazenamento da entrega Users.
- RNF02/RF03: autenticação no servidor e infraestrutura RBAC disponíveis;
  falta aplicar a matriz a todos os endpoints de negócio.
- RF19.2: usuário inativo é bloqueado a cada acesso; o gerenciamento
  administrativo abaixo desativa a conta e revoga suas sessões definitivamente.
- RNF09: tratamento técnico de falhas e sigilo; fluxos futuros de importação
  deverão reutilizar o tratamento e verificar seus próprios cenários.

Não há cadastro público, UI de login,
limitação distribuída de tentativas ou renovação automática de sessão.
As integrações usam exclusivamente `mini_soc_test`, com schemas isolados e
rollback, incluindo comparação entre migration e metadata. Não comprovam
recuperação após reinício real do banco/aplicação. spec.md e ADR permanecem
como fonte de escopo e arquitetura.

Enquanto o PR #15 estiver aberto, o PR de autenticação usa
`codex/persistencia-users` como base. Após sua integração, deve ser
reconciliado com main e ter a base atualizada, preservando o histórico.

## Autorização por papéis — Issue #18

`app/auth/authorization.py` fornece a fábrica `require_roles`. Ela recebe
somente valores de `UserRole`, cria um conjunto imutável de papéis permitidos
e retorna uma dependência FastAPI. A dependência primeiro reutiliza
`get_current_user`, que consulta a sessão e o User no banco, e depois
compara o papel atual com os papéis explicitamente permitidos.

Para configurar uma rota real, inclua na sua lista `dependencies` uma
das dependências abaixo, conforme a operação da seção 2 de spec.md:

```python
from fastapi import Depends
from app.auth.authorization import require_roles
from app.users.models import UserRole

admin_only = Depends(require_roles(UserRole.ADMIN))
analyst_only = Depends(require_roles(UserRole.ANALYST))
shared = Depends(require_roles(UserRole.ADMIN, UserRole.ANALYST))
```

Se o handler também precisar do User, utilize
`Annotated[User, Depends(require_roles(...))]` em sua assinatura, escolhendo
explicitamente os papéis. Não passe strings, nomes recebidos do cliente ou
uma lista vazia: configuração inválida é rejeitada com ValueError durante
o registro da rota. Papéis repetidos são consolidados, sem ampliar acesso.

| Operação futura | Papéis permitidos |
|---|---|
| Consultar Logs | ADMIN e ANALYST |
| Importar Logs | ADMIN |
| Cadastrar, alterar e desativar Users ou Assets | ADMIN |
| Ativar/desativar Detection Rules | ADMIN |
| Consultar Audit Logs | ADMIN |
| Consultar/investigar/descartar/escalonar Alerts | ANALYST |
| Investigar e registrar evidências | ANALYST |
| Consultar, abrir, tratar e resolver Incidents | ANALYST |
| Consultar Dashboard | ANALYST |

ADMIN não herda permissões de ANALYST. Uma operação compartilhada precisa
listar ambos. O papel não vem do cookie, JSON, query string ou header do
cliente, mas do User consultado no banco. Mudanças no papel são refletidas
no próximo acesso, sem exigir novo login ou copiar permissões para a sessão.

Sem autenticação válida, a dependência preserva o HTTP 401 de
`get_current_user`, incluindo sessão expirada/revogada e User INACTIVE.
Com autenticação válida, um papel não permitido recebe HTTP 403 com
`Permissão insuficiente.`. Em ambos os casos, o handler não é executado.
Nas escritas, Origin e CSRF continuam obrigatórios antes da autorização;
uma configuração RBAC não substitui nem contorna essas verificações.

### Evidência e integrações pendentes

Os testes criam aplicações FastAPI próprias com rotas temporárias
`/probe/*`, sem adicioná-las ao app de produção. Usam as sessões reais e
Users persistidos nos schemas isolados de `mini_soc_test`, inclusive para
simular mudança de papel e inatividade diretamente no banco.

RF03 e RNF02 estão atendidos pela infraestrutura reutilizável e pelos
cenários isolados, mas não são declarados integralmente concluídos no MVP.
Os endpoints de Assets, Logs, Detection Rules, Alerts, Investigations,
Incidents, Dashboard e Audit Logs ainda precisam integrar as dependências
apropriadas quando forem implementados. Login, consulta do próprio perfil
e logout continuam com as proteções de autenticação/CSRF existentes, sem
restrição administrativa adicional. O health check permanece público.
As rotas administrativas de Users da Issue #21 já usam ADMIN explicitamente.

Essa entrega de infraestrutura RBAC não criou endpoints de negócio, alteração de papéis, auditoria,
JWT, tabelas ou migrations e não altera o código da Pessoa 2. O app de
produção não registra automaticamente as permissões da tabela acima: cada
rota futura precisa declarar sua dependência explicitamente.

Na verificação desta entrega, #15 estava integrado à main, mas #17 foi
integrado somente em `codex/persistencia-users`; a main ainda não possuía
autenticação. Por isso, `feat/autorizacao-papeis` usa `codex/autenticacao`
como base do PR, preservando o diff somente de RBAC. A promoção da
autenticação para main e a reconciliação posterior da pilha seguem pendentes.

## Gerenciamento administrativo de Users — Issue #21

Todas as rotas abaixo exigem sessão válida, User ACTIVE, papel ADMIN,
Origin configurado e X-CSRF-Token da sessão. Não existe cadastro público.
As respostas contêm somente id, username, role e status, com no-store.

| Endpoint | Entrada e resultado |
|---|---|
| `POST /users` | JSON username, role (ADMIN/ANALYST) e password; cria UUID e ACTIVE; retorna 201. |
| `PATCH /users/{user_id}` | JSON com username e/ou role de outro User; preserva UUID e associações; retorna 200. |
| `POST /users/{user_id}/deactivate` | Desativa sem excluir, revoga todas as sessões e retorna 200. |

Campos desconhecidos, valores nulos em alteração, papel inválido e valores
vazios são rejeitados com 422 genérico, sem eco do corpo. Username duplicado
retorna 409, inclusive pela constraint do banco. User inexistente retorna
404. Um PATCH deve informar ao menos um campo; repetir valores já atuais
retorna 200 sem gerar auditoria adicional. Desativação de conta já INACTIVE
retorna 409 sem novo registro. Não há alteração de senha ou reativação.

RF30 cobre outra conta: alteração do próprio username ou papel é recusada
com 403. RF25 impede a alteração do próprio papel mesmo quando há outros
administradores. A autodesativação é permitida somente quando resta outro
ADMIN ACTIVE. O último ADMIN ACTIVE não pode ser desativado (409); sua
mudança de papel também é bloqueada pela regra de edição da própria conta.

### Transações e concorrência

As operações usam o mesmo Session/Engine da aplicação. O Engine explicita
READ COMMITTED: depois de esperar um lock, uma nova consulta vê o estado
confirmado atual. O serviço obtém pg_advisory_xact_lock com chave fixa de
escrita de Users, reconsulta o autor e depois bloqueia a linha do alvo com
FOR UPDATE. A contagem de administradores ocorre dentro dessa seção
serializada. Assim, duas requisições não aprovam a remoção de administradores
com base na mesma contagem antiga. O lock termina no commit/rollback.

Todos os futuros caminhos que alterem papel/estado de User devem reutilizar
esse protocolo de serialização. Ele protege as operações do servidor, não
escritas arbitrárias realizadas diretamente por um administrador do banco.
O lock_timeout da transação é de cinco segundos; uma falha de lock não
confirma alterações parciais. Não há repetição automática de operações.

O login bloqueia a linha do User antes de verificar credenciais e mantém
o lock até terminar a transação. A desativação usa o mesmo lock de linha:
ou um login anterior confirma sua sessão e ela é revogada pela desativação,
ou a desativação confirma primeiro e o login encontra INACTIVE. Nenhuma
sessão é emitida usando uma leitura antiga após a revogação dessa conta.

Alteração de estado, revogação e auditoria usam uma única transação. Falha
em qualquer etapa reverte tudo. Sessões revogadas continuam inválidas mesmo
se o estado for restaurado por um procedimento externo; isso é testado
sem adicionar endpoint de reativação. Alteração de papel vale na próxima
requisição autenticada, sem copiar papéis para cookies ou sessões.

### Contrato compartilhado de auditoria

Audit Log não existia nas branches remotas verificadas. O módulo
`app/audit` adiciona a estrutura mínima compartilhada e a função interna
`append_audit`, que apenas acrescenta um registro na Session recebida, sem
commit próprio. Quem executa a operação deve confirmar ou reverter a
alteração de negócio e a auditoria juntas.

| Campo | Contrato |
|---|---|
| id | UUID do registro, gerado na aplicação. |
| author_id | UUID do User autor; FK RESTRICT preserva a associação histórica. |
| action | Ação definida pelo serviço, nunca copiada de entrada livre do cliente. |
| entity_type | Tipo de entidade; nesta entrega USER. |
| entity_id | Identificador textual, permitindo UUIDs de User e identificadores futuros de outros módulos. |
| occurred_at | Data/hora UTC com fuso. |
| old_role / new_role | Ambos nulos ou ambos preenchidos com ADMIN/ANALYST; somente quando há mudança de papel. |

As ações desta entrega são USER_CREATED, USER_UPDATED e USER_DEACTIVATED.
Cada operação efetiva gera exatamente um registro. Alterar username e
papel juntos gera um único USER_UPDATED com os dois papéis, conforme RF26.
Não existe campo livre de payload ou senha, token ou hash no registro.

Assets, Detection Rules, Alerts e Incidents poderão usar append_audit com
suas ações e identificadores no futuro, preservando a transação do serviço.
Somente operações de Users são auditadas agora. Não existem endpoints de
alteração/exclusão de Audit Logs; a consulta RF28 está descrita na Issue #23 abaixo.
RNF04 é atendido pelas interfaces disponibilizadas; não há trigger ou
privilégio SQL prometendo imutabilidade contra acesso direto ao PostgreSQL.

### Migration, validação e requisitos

`0003_create_audit_logs` depende de `0002_create_auth_sessions` e cria apenas
audit_logs com suas constraints. Nenhuma tabela de Users/sessões é recriada.
O metadata compartilha Base; o downgrade destrutivo é bloqueado. Revise a
migration antes de aplicá-la. Nesta entrega ela é executada somente nos
schemas isolados dos testes em mini_soc_test, com rollback, sem aplicação
em desenvolvimento. A comparação automática de metadata deve permanecer
sem diferenças e o Alembic com uma única head.

Os testes incluem RBAC e CSRF nas três rotas, Argon2id, duplicação, edição,
último ADMIN, revogação, auditoria única e rollback de falhas após flush.
O teste de concorrência usa duas transações físicas de PostgreSQL: uma
espera pelo lock da outra e só prossegue após sua liberação. A preservação
do último ADMIN é verificada com operações subsequentes sobre o mesmo
estado. Não é declarado um teste end-to-end de duas mutações HTTP paralelas
em dados compartilhados: isso exigiria confirmar dados fora dos schemas
transacionais reversíveis usados pela suíte. Não há limpeza destrutiva.

RF19.1, RF19.2, RF25, RF26, RF30 e RF31 são implementados para estes fluxos.
RF15.1 cobre Users; Assets e regras continuam pendentes. RNF01 e RNF02/RF03
são aplicados nestas rotas, sem declarar a matriz completa do MVP atendida.
Reset de senha, reativação, UI e auditoria dos outros módulos permanecem
fora desta entrega. Listagem de Users e RF28 são adicionados na Issue #23.
spec.md e ADR são preservados.

Integração: PR #20 propõe codex/autenticacao -> main usando o commit
existente de autenticação, sem duplicação. O gerenciamento de Users usa
feat/autorizacao-papeis como base enquanto o PR #19 estiver aberto. Nenhum
merge é executado automaticamente por esta entrega.

## Consultas administrativas — Issue #23

As duas consultas exigem sessão válida, User ACTIVE e papel ADMIN,
reutilizando get_current_user e require_roles. Usuário sem autenticação
válida recebe 401; ANALYST recebe 403. São operações GET sem escrita,
portanto não exigem Origin ou token CSRF. As escritas anteriores mantêm
suas verificações, e CORS não é liberado. As respostas usam no-store.

| Endpoint | Conteúdo e ordenação |
|---|---|
| `GET /users` | id, username, role e status; username ASC e id ASC. |
| `GET /audit-logs` | id, author_id, action, entity_type, entity_id, occurred_at, old_role e new_role; occurred_at DESC e id DESC. |

GET /users é uma funcionalidade administrativa complementar para a futura
interface. Não existe um RF específico de listagem de Users na spec, e
esta entrega não atribui um requisito inexistente à funcionalidade.

Em GET /users, os filtros opcionais role (ADMIN/ANALYST) e status
(ACTIVE/INACTIVE) são combinados com AND. O total representa somente os
registros correspondentes. User INACTIVE pode aparecer na listagem,
mas não pode autenticar-se nem consultar os endpoints.

### Paginação e parâmetros

Ambos aceitam page, de 1 a 10.000, e page_size, de 1 a 100. Os padrões são
page=1 e page_size=20. Offset e limite são aplicados pelo PostgreSQL, sem
carregar a lista completa para paginar em Python. Uma página válida além
do fim retorna items vazio e mantém o total, sem erro 404.

As respostas têm o mesmo envelope:

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20
}
```

Exemplos de consulta: `/users?role=ANALYST&status=INACTIVE&page_size=20`
e `/audit-logs?page=2&page_size=20`. Papel/estado inválidos, páginas fora
dos limites, valores não inteiros e parâmetros desconhecidos retornam
422 genérico, sem eco de entradas. Não há filtros extras de auditoria.

A ordenação total inclui UUID para desempatar; em auditoria, dois eventos
com occurred_at igual mantêm uma ordem determinística. Isso não cria um
snapshot entre requisições. Total e itens usam SELECTs separados em READ
COMMITTED: inserções/alterações concorrentes podem mudar páginas ou totais.
Paginação por cursor ou snapshot estável não faz parte desta entrega.

### Sigilo, preservação e arquitetura

Os repositórios selecionam explicitamente apenas as colunas públicas.
Schemas Pydantic controlam os campos de resposta; Users não incluem
password_hash nem dados de sessões. Auditoria retorna o identificador do
autor, sem juntar credenciais ou dados privados do User. old_role e
new_role são nulos quando não há mudança de papel no evento persistido.

As consultas não executam commit, não alteram os registros e não criam
Audit Logs. O teste de leitura verifica os comandos SQL emitidos e compara
os registros completos antes/depois. Não há POST/PATCH/PUT/DELETE de
auditoria: tentativas na coleção recebem 405 e não modificam dados; as
rotas de detalhe de mutação continuam inexistentes. RNF04 cobre as APIs
disponibilizadas, sem prometer imutabilidade contra SQL direto no banco.

API, validação de parâmetros, serviços e repositórios permanecem separados.
O módulo compartilhado core/pagination contém apenas os limites de entrada
e o envelope de resposta tipado; não adiciona um framework de consultas.
User, AuditLog, Session Factory e os mecanismos de segurança são reutilizados.
Não há migration, dependência externa ou alteração na estrutura do banco.

RF28 é implementado pela consulta dos Audit Logs persistidos. RNF02/RF03
são aplicados às duas rotas; a matriz inteira do MVP ainda depende das
integrações dos demais módulos. RNF04 é preservado pela ausência de APIs
de mutação e pelos testes de leitura sem efeitos colaterais.

Os testes AAA cobrem ADMIN, ANALYST e anônimo, ordenação, filtros AND,
paginação após filtros, páginas vazias, limites, desempate, campos corretos,
sigilo e proteção contra mutação. Integração exclusivamente em mini_soc_test,
com schemas isolados e rollback, preservando as regressões anteriores.

feat/consultas-administrativas usa feat/gerenciamento-usuarios como base
enquanto #22 estiver aberto. A ordem proposta continua #20 (autenticação),
reconciliação de #19 (RBAC), #22 (gerenciamento) e o PR destas consultas.
Nenhum merge ou reescrita de histórico é realizado automaticamente.

## Estado da entrega de persistência — Issue #7

- Conexão PostgreSQL com SQLAlchemy e Psycopg, configuração externa,
  Engine e fábrica de sessões centralizados e estrutura inicial do Alembic.
- Testes de conexão, validação da configuração, commit, rollback e descarte
  de gravações pendentes ao encerrar a dependência de sessão.
- **RNF03:** infraestrutura disponível; a recuperação completa das entidades após
  reinício da aplicação ainda precisa ser implementada e verificada.
- **RF11:** suporte a transações disponível; o escalonamento atômico de Alert
  para Incident permanece para a Issue desse fluxo.
- **CE01:** instruções de instalação, configuração, banco e execução
  documentadas; a reprodução completa do MVP depende das próximas entregas.

Essa infraestrutura segue o monólito modular definido no ADR-001. Os testes
com tabelas temporárias verificam transações entre sessões na mesma conexão;
não demonstram durabilidade das entidades após reconexão ou reinício.
