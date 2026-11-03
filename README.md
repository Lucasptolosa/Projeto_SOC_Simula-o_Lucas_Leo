# Mini SOC

## Assets - Issue #38

O módulo `app/assets` implementa cadastro, alteração de nome/tipo e desativação
de Assets. Reutiliza a Base, Settings, Engine, Session Factory, autenticação,
RBAC e auditoria já integrados à main pelo PR #36. Não há infraestrutura paralela.

| Endpoint | Papel | Comportamento |
|---|---|---|
| `POST /assets` | ADMIN | Recebe name/type/status, gera UUID e retorna HTTP 201. |
| `PATCH /assets/{id}` | ADMIN | Altera somente name/type, inclusive em inativos; HTTP 200. |
| `POST /assets/{id}/deactivate` | ADMIN | Altera para INACTIVE; repetição retorna estado atual sem novo Audit Log. |

As respostas contêm somente id/name/type/status e usam Cache-Control: no-store.
Nome é obrigatório e não pode conter somente whitespace, sem normalização,
unicidade ou limite de tamanho adicional. Tipos/estados seguem exatamente a spec.
Campos extras, nulls explícitos, PATCH vazio e alterações de id/status são rejeitados.
Não há reativação, exclusão física, interface web ou consulta/listagem nesta entrega.

Serviços não fazem commit. O endpoint valida a resposta e confirma uma única
transação após a gravação de Asset e Audit Log; qualquer falha provoca rollback.
`append_audit` é reutilizado com entity_type ASSET e ações ASSET_CREATED,
ASSET_UPDATED ou ASSET_DEACTIVATED, com old_role/new_role nulos.
Operações que não mudam dados não geram auditoria de mutação inexistente.

As escritas reutilizam o lock transacional administrativo existente para conferir
o autor atual em coordenação com mudanças de papel/estado. Atualização e
desativação também bloqueiam a linha do Asset, evitando alterações concorrentes
baseadas em estado desatualizado. Origin e CSRF existentes são obrigatórios.

Migration `0004_create_assets`, após `0003_create_audit_logs`: cria somente assets,
com UUID, nome, tipo, estado e constraints nomeadas. Não altera Users, AuthSession
ou AuditLog. O modelo é registrado no metadata compartilhado do Alembic.
Não foi aplicada migration em mini_soc_dev. Downgrade destrutivo é bloqueado,
seguindo a política existente de preservação dos dados.

### Rastreabilidade e validação de Assets

| Requisito | Entrega e limite |
|---|---|
| RF04 | Cadastro persistente e UUID gerado no servidor. |
| RF29 | Alteração de nome/tipo preserva id/status e histórico de auditoria. |
| RF05 | Desativação sem exclusão; repetição idempotente sem nova auditoria. |
| RF03/RNF02 | API protegida por ADMIN e autor ativo conferido no serviço. |
| RF15.1 | Auditoria compartilhada, atômica com a mutação do Asset. |
| RN05 | Não há exclusão física/cascata de Assets; integração com evidências de Logs/Alerts permanece futura. |
| RNF03 | Integridade/leitura entre sessões testadas em PostgreSQL; reinício real e recuperação integral do MVP não comprovados. |

Os contratos estão na seção 3.2 da spec. Testes de contrato e integração seguem
AAA, com positivos, negativos, permissões, estado inativo, repetições e rollback
provocado por falhas reais de constraints e falha da auditoria após flush.
O teste de metadata existente foi atualizado apenas para a nova tabela/head.

Validação da entrega no Python 3.14.10: 460 testes aprovados em 140,38 s,
99,14% de cobertura geral e 100% de cobertura de linhas em Assets. A suíte inclui
103 casos de Assets (42 de contrato e 61 de integração), regressões existentes
e testes web com Chromium real. O primeiro passe específico de Assets, antes
dos dois últimos casos de constraints, também mediu 100% de linhas/ramificações.
As dependências declaradas foram conferidas com uv pip check, sem incompatibilidades.
Resultado de CI remoto ainda não confirmado; estes são resultados locais.

Os testes foram executados sobre snapshot exato da main 1f29969 mais a entrega
da #38, em cluster PostgreSQL 17.11 portátil separado, vinculado somente ao
loopback e usando mini_soc_test com role NOSUPERUSER/NOCREATEDB/NOCREATEROLE.
O conteúdo Python final do clone foi conferido contra o snapshot testado.
Nenhuma instalação, credencial ou banco de desenvolvimento foi utilizado.

Dentro de backend, com `.env.test` apontando exclusivamente para mini_soc_test:

```powershell
python -m pytest tests/test_asset_contracts.py tests/test_assets.py --cov=app.assets --cov-branch --cov-report=term-missing -q
python -m pytest --cov=app --cov-report=term-missing --cov-fail-under=70 -q
```

As fixtures existentes verificam o nome configurado e o banco real antes de
qualquer escrita; usam schemas aleatórios, transação externa, savepoints e
rollback. Não compartilhar credenciais ou usar mini_soc_dev nos testes.

Permanecem fora desta entrega: importação de Logs, ingestão em Asset inativo,
persistência/consulta de Alerts, Dashboard e teste de desempenho do MVP.
Logs/Alerts ainda não têm modelos persistentes: não se afirma que a preservação
de suas associações com Asset já tenha sido testada.

Sistema acadêmico de monitoramento de segurança, desenvolvido para receber logs simulados, aplicar regras de detecção, gerar alertas e permitir a investigação e o tratamento de incidentes.

Projeto de Modelagem de Sistemas desenvolvido por Lucas e Leonardo.
O escopo é definido em [spec.md](spec.md) e a arquitetura no
[ADR-001](docs/adr/01-arquitetura-inicial.md).

## Estado da integração

A main verificada em fc97bb2 contém persistência de Users, autenticação,
RBAC e as Detection Rules atualizadas pelo PR #37; a Issue #35 foi encerrada.
Esta branch integracao/administracao-web prepara a promoção das
funcionalidades administrativas e web das Issues #21, #23, #25 e #27,
ainda ausentes da main. Um PR merged em branch intermediária não conclui
essa integração. A Issue #18 foi regularizada após validação na main.

O [diagnóstico de integração](docs/estado-integracao.md) lista todas as
Issues/PRs verificados, os commits reaplicados, a reconciliação dos PRs #32
e #34, os resultados dos testes e a ordem de revisão. A sequência proposta
é CI #30, administração/web, Incidents #32 e Investigations #34; os dois
últimos são independentes. Nenhum merge na main foi executado nesta tarefa.

## Tecnologias

- Python 3.14 (ambiente validado com Python 3.14.8)
- FastAPI
- PostgreSQL
- SQLAlchemy
- Psycopg
- Alembic
- pytest
- Jinja2, HTML, CSS e JavaScript

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

Consulte também o contrato e os testes das
[regras de Investigation e False Positive](docs/regras-investigacoes.md).

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

## Integração contínua — Issue #29

CI (integração contínua) executa verificações automaticamente para detectar
regressões antes da integração. O workflow `.github/workflows/testes.yml`
executa em abertura, atualização e reabertura de Pull Requests e em pushes
na main. Não há filtro de branch-base para PRs: também aceita PRs empilhados
quando o workflow estiver presente no checkout correspondente.

O job Pytest e cobertura usa Ubuntu 24.04 e Python 3.14, instala as
dependências de `backend/requirements-dev.txt` do próprio checkout e executa
toda a suíte disponível. No evento pull_request, o checkout padrão testa o
commit de integração proposto pelo GitHub, incluindo a base do PR. Nenhum
módulo de autenticação, interface ou outro PR futuro é exigido pela CI.

Após instalar as dependências, o workflow procura o pacote Playwright.
Quando presente, instala Chromium e suas dependências Linux por
`python -m playwright install --with-deps chromium`. Na main atual esse
pacote não é exigido, então essa etapa é omitida; testes não são filtrados
ou ignorados pela CI. Se um commit adicionar testes web sem declarar suas
dependências, a coleta de testes deve falhar normalmente.

### Resultado e reprodução

Na aba Checks do PR ou Actions do repositório, abra Testes Mini SOC e o job
Pytest e cobertura. Verde significa que instalação, banco, suíte inteira e
cobertura mínima foram aprovados. Vermelho indica falha em alguma etapa;
abra seu log e verifique o teste/etapa indicado. Cancelado pode significar
que uma nova atualização do mesmo PR substituiu a execução anterior.
Não há continue-on-error ou supressão do código de saída do pytest.

A cobertura aparece no log de Executar suíte completa. O comando é:

```powershell
python -m pytest --cov=app --cov-report=term-missing --cov-fail-under=70 --tb=no --show-capture=no -q
```

Execute na pasta backend com o ambiente virtual ativo, dependências daquele
commit instaladas e seu `.env.test` local apontando somente para
mini_soc_test, conforme as instruções anteriores. Se o commit incluir
Playwright, instale Chromium localmente com `python -m playwright install chromium`.
No Linux, `--with-deps` também instala as bibliotecas do navegador; o runner
faz essa instalação automaticamente. Não execute o script de preparo da CI
no seu PostgreSQL local: ele é restrito ao serviço descartável do runner.

Os flags --tb=no e --show-capture=no reduzem a exposição de dados de fixtures
em falhas, mantendo o nome dos testes reprovados e o código de erro. Para
investigar localmente, use as instruções de pytest anteriores em ambiente
controlado, sem publicar senhas, hashes ou cookies em relatórios.
A meta geral continua 70%; as metas específicas da spec continuam válidas.
Cobertura Python não mede instruções JavaScript ou conformidade completa do MVP.

### Banco isolado e credenciais

Cada job recebe um serviço oficial postgres:17-bookworm sem volume de dados
do usuário e com a porta publicada somente em 127.0.0.1 no runner. O único
banco de aplicação criado é mini_soc_test; bancos internos padrão do
PostgreSQL não são usados pela suíte. Não há conexão com mini_soc_dev,
PostgreSQL local, produção ou secrets pessoais.

O entrypoint inicial usa autenticação temporária trust no serviço de loopback
para permitir o bootstrap sem senha fixa versionada. Antes de executar
dependências/testes, `.github/scripts/prepare_test_database.py` confirma que
está em runner GitHub hospedado, valida container/imagem/porta e nome real do
banco, cria a role mini_soc_app e substitui a autenticação TCP por SCRAM-SHA-256.
Login TCP de postgres e acesso a outros bancos/roles são recusados. O
bootstrap administrativo fica acessível somente pelo socket dentro do
container. O script não aceita host ou banco de outro ambiente.

A role da aplicação tem LOGIN, NOSUPERUSER, NOCREATEDB, NOCREATEROLE,
NOREPLICATION e NOBYPASSRLS. Como proprietária de mini_soc_test, pode criar
schemas e tabelas temporárias exigidos pelas fixtures. O job verifica essa
role e suas permissões usando uma conexão real antes do pytest.

A senha é aleatória por execução e mascarada antes de qualquer uso. O
arquivo backend/.env.test é criado somente no runner, com permissão 0600,
e removido após o job; um arquivo preexistente não é sobrescrito pelo
preparo. As variáveis DB_* do job também apontam exclusivamente para esse
banco. As fixtures continuam recusando DB_NAME diferente de mini_soc_test
e confirmando SELECT current_database() antes de criar objetos de teste.

As migrations existentes são executadas pelas fixtures somente em schemas
aleatórios dentro de transações reversíveis; o workflow não aplica upgrade
em banco permanente. Os dados/serviço são descartados com o runner. Não há
upload de dotenv, dumps, coverage bruto, screenshots, traces, vídeos ou
outros artefatos de teste que possam conter dados sensíveis.

### Permissões e integração

O GITHUB_TOKEN recebe somente contents: read. O checkout não persiste a
credencial Git, e código de PR roda em pull_request, sem pull_request_target.
As duas Actions oficiais são fixadas pelo SHA de versões verificadas:
[checkout v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1) e
[setup-python v7.1.0](https://github.com/actions/setup-python/releases/tag/v7.1.0).
A fixação segue a [orientação de segurança do GitHub](https://docs.github.com/en/actions/reference/security/secure-use).
O job tem limite de 20 minutos e cancela execuções anteriores do mesmo PR/ref.

Esta entrega parte da main e não depende dos PRs #20, #19, #22, #24, #26 ou
#28. Adicionar CI à main não copia o arquivo automaticamente para branches
antigas da pilha; depois da integração, será necessário reconciliar essas
branches/bases para que seus checkouts incluam o workflow, preservando a
ordem dos PRs. Nenhuma branch de funcionalidade é alterada por esta entrega.
Tornar o check obrigatório na proteção da main é uma decisão posterior do
responsável pelo repositório; abrir este PR não modifica essas configurações.

O ambiente local documentado é Windows/Python 3.14.8, com caminhos e ativação
PowerShell. O runner usa Linux, bash, caminhos POSIX, PostgreSQL em serviço
Docker e instalação das bibliotecas Chromium via apt. Os comandos Python e
as guardas do banco são compartilhados. Aprovação local não substitui uma
execução real no GitHub; o resultado remoto e seu link são registrados no PR.

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
Os endpoints futuros de Logs, Detection Rules, Alerts, Investigations,
Incidents e Dashboard ainda precisam integrar as dependências
apropriadas quando forem implementados. Login, consulta do próprio perfil
e logout continuam com as proteções de autenticação/CSRF existentes, sem
restrição administrativa adicional. O health check permanece público.
As rotas administrativas de Users da Issue #21 e de Assets da Issue #38 já usam
ADMIN explicitamente. A consulta de Audit Logs também usa ADMIN no servidor.

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
RF15.1 cobre Users e, na Issue #38, Assets; regras continuam pendentes. RNF01 e RNF02/RF03
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

## Interface web — Issue #25

A interface usa Jinja2 com autoescape, HTML, CSS e JavaScript locais no mesmo
monólito FastAPI (ADR-001). Não exige Node, build ou framework de front-end.
Jinja2 é a única dependência nova de execução. Playwright é exclusivo dos
testes de navegador; não participa da aplicação em produção.

| Página | Acesso e comportamento |
|---|---|
| `/` | Redireciona para `/app`. |
| `/login` | Pública; username/senha via JSON em POST /auth/login. |
| `/app` | Sessão válida e User ACTIVE; identidade/papel por GET /auth/me. |
| `/app/users` | Somente ADMIN; GET /users, filtros de papel/estado e paginação. |
| `/app/audit-logs` | Somente ADMIN; GET /audit-logs, paginação e histórico recente primeiro. |

### Acesso local

Instale as dependências atualizadas. Utilize um banco de desenvolvimento já
preparado pelas migrations anteriores e uma conta criada pelo procedimento
de Administrator inicial acima. Esta entrega não cria conta, migration ou
credencial padrão e não aplica migrations automaticamente.

O endereço aberto no navegador deve corresponder exatamente a AUTH_ORIGIN,
incluindo esquema, host e porta. Para desenvolvimento **exclusivamente em
loopback HTTP**, configure no ambiente local ignorado pelo Git:

```dotenv
AUTH_ORIGIN=http://127.0.0.1:8000
AUTH_COOKIE_SECURE=false
```

Na pasta backend, execute `python -m uvicorn app.main:app --reload` e abra
[a página de login](http://127.0.0.1:8000/login). Não troque 127.0.0.1 por
localhost sem ajustar AUTH_ORIGIN. A permissão existente de cookie sem
Secure continua limitada a HTTP loopback. Em implantação, use HTTPS, origem
correta e AUTH_COOKIE_SECURE=true (padrão); não exponha o servidor de
desenvolvimento ou use esse exemplo HTTP em rede externa.

### Organização e comportamento

`backend/app/web/router.py` contém somente rotas de apresentação. Templates
em `app/web/templates`: base.html (documento e recursos), login.html,
shell.html (navegação autenticada), home.html, users.html, audit.html,
pagination.html (fragmento compartilhado) e forbidden.html. `app/web/static`
contém web.css e web.js, servidos em /static. Não há consulta SQL nos
templates ou duplicação dos serviços de negócio.

O servidor reutiliza get_current_user e require_roles. Páginas sem sessão
válida redirecionam para o login; páginas administrativas negam ANALYST
com 403 antes de renderizar seu conteúdo. APIs mantêm 401/403 e o contrato
JSON anterior. O contexto Jinja contém somente flags/título/nome da página,
nunca o objeto ORM, senha ou tokens. A identidade é recuperada por /auth/me.

ADMIN encontra consultas reais de Users e auditoria. ANALYST vê sua conta
e uma indicação de que ainda não há consultas disponíveis nesta entrega;
não há links fictícios de Alerts/Investigations ou dashboard analítico.
O gerenciamento visual de Users utiliza as operações existentes na API,
conforme a Issue #27 descrita abaixo. Auditoria permanece somente leitura.

Users mostra username, ADMIN/ANALYST e ACTIVE/INACTIVE textuais, filtros
combinados e controles de página. Mudar filtros ou tamanho reinicia na
página 1. O padrão é 20 itens, com opções 10/20/50/100 e teto de página
10.000, respeitando a API. Auditoria mostra o **identificador do autor**,
ação, tipo/identificador da entidade, horário e papel anterior/novo quando
presentes. Não inventa nome histórico do autor nem busca usuários por linha.
A ordem retornada pela API é preservada (occurred_at DESC, id DESC).
Datas são formatadas em português no fuso America/Sao_Paulo, com indicação
na tela; o timestamp persistido não é alterado. Ausência de valores aparece
como travessão. As limitações de paginação concorrente da API permanecem.

### Segurança e erros

- fetch usa credentials: same-origin e cache: no-store, sem CORS novo.
- O navegador fornece Origin no login/logout. O JavaScript não define esse
  header e não cria outro mecanismo de autenticação.
- Sessão permanece em cookie HttpOnly/Secure/SameSite=Strict. Não há JWT,
  token de sessão em storage, URLs ou HTML. O token CSRF de /auth/me fica
  somente na memória do script e é enviado no header X-CSRF-Token do logout.
- Logout só confirma a saída após revogação no servidor; falhas mostram
  feedback e não simulam sucesso. 401 conduz ao login. Expiração, revogação
  e INACTIVE são revalidados no servidor em cada acesso; ao retornar à aba,
  /auth/me também é reconsultado. Páginas restauradas do histórico recarregam.
- Senha é limpa do campo após cada tentativa. Login inválido/inativo recebe
  mensagem genérica; erros de API não exibem detalhes internos. Requisições
  têm limite de espera de 15 segundos e permitem nova tentativa.
- Sem JavaScript inline ou innerHTML. Dados de API são inseridos usando
  textContent. CSP das páginas limita scripts/estilos/conexões à própria
  origem, bloqueia frames, base e submissão nativa de formulário. Sem JS,
  um aviso é mostrado e credenciais não são submetidas por navegação.
- Páginas e recursos usam no-store, nosniff e no-referrer. Nenhum dado
  de conta/sessão é embutido nos arquivos estáticos.

Os controles visuais complementam o RBAC das páginas e APIs; não concedem
permissão. A consulta de auditoria não cria, edita nem exclui eventos.
RF01/RF02 são integrados pela tela, RF03/RNF02 pela autorização deste escopo,
RF28 pela consulta e RNF04 pela preservação. RNF01/RNF09 e RF19.2 permanecem
protegidos pelos componentes existentes e testes. A listagem de Users é
complementar, sem RF específico; a matriz inteira do MVP continua pendente.

### Testes e validação visual

Após instalar requirements-dev.txt, instale uma vez o navegador de testes:

```powershell
python -m playwright install chromium
python -m pytest tests/test_web.py -q
python -m pytest --cov=app --cov-report=term-missing --cov-fail-under=70 -q
```

Os testes pytest executam o JavaScript em Chromium real. O transporte das
requisições é direcionado ao app ASGI via TestClient, com os cookies e headers
Origin produzidos pelo navegador, sem servidor externo ou certificado de
teste. As APIs e o PostgreSQL são reais; somente cenários explícitos de erro
interceptam respostas. O cookie jar do TestClient é esvaziado a cada envio
para que somente o cookie do navegador autentique o fluxo. Integrações usam
exclusivamente mini_soc_test, schemas aleatórios e rollback, reutilizando as
fixtures anteriores. Nenhum usuário ou registro permanente é criado.

Validação desta entrega: **286 testes aprovados**, incluindo 38 novos
cenários web e todas as 248 regressões anteriores. Cobertura Python de app:
**98,56%** (763 instruções, 11 não cobertas), acima da meta de 70%.

A cobertura pytest-cov mede **Python**, não cobertura de instruções JS/CSS
ou acessibilidade completa. A suíte inclui fluxos reais de login/logout,
cookies/CSRF, páginas protegidas, filtros, paginação, listas vazias, erros,
sigilo, XSS, sessão invalidada e atualização de papel. As regressões das
entregas anteriores continuam obrigatórias.

Roteiro manual para a Pessoa 2, com contas próprias no ambiente local:

1. Abrir /login em desktop e largura móvel (390 px). Usar Tab/Enter, verificar
   labels, foco visível, link de pular conteúdo, contraste e ausência de corte.
2. Informar senha incorreta e conta inativa: mensagem genérica e campo limpo.
   Testar indisponibilidade da API pelo DevTools, sem registrar credenciais.
3. Entrar como ADMIN. Conferir username/papel e navegar para Users. Combinar
   filtros, mudar tamanho, avançar/voltar e obter uma consulta sem resultados.
4. Conferir auditoria com dados reais: autor por ID, ação, entidade, papéis,
   horário em America/Sao_Paulo e ordem recente; em móvel, rolar só a tabela.
5. Sair e tentar voltar/recarregar. Invalidar uma sessão pelo fluxo suportado
   ou aguardar expiração e confirmar retorno ao login, sem dados restritos.
6. Entrar como ANALYST: sem consultas administrativas; abrir suas URLs
   diretamente deve retornar 403. APIs também devem negar o acesso.
7. Pelo DevTools, conferir cookie HttpOnly/SameSite e Secure em HTTPS,
   storage vazio, POST JSON de login e CSRF no logout. Não copiar tokens
   para screenshots, relatórios ou Git. Conferir ausência de erros no console.

Revisão manual com leitor de tela e validação de proxy/TLS real continuam
recomendadas; o transporte ASGI da suíte não testa a implantação HTTPS.
Esta branch depende de #24 -> #22 -> #19, além da promoção de autenticação
em #20. Nenhum merge ou alteração de código da Pessoa 2 é realizado.

## Gerenciamento visual de Users — Issue #27

Em `/app/users`, ADMIN pode cadastrar, editar e desativar contas usando as
APIs existentes. A página continua protegida por require_roles no servidor;
ANALYST não recebe os formulários ou ações. Não há cadastro público.

| Ação visual | Integração e campos |
|---|---|
| Novo usuário | POST /users com username, role e password; nova conta ACTIVE. |
| Editar | PATCH /users/{id} com somente username e role; sem senha/status/UUID editáveis. |
| Desativar | POST /users/{id}/deactivate após confirmação explícita. |

O cadastro exige confirmação de senha no navegador; esse campo **não é
enviado à API**. Campos obrigatórios/brancos e senhas divergentes recebem
validação visual, sem normalizar ou truncar os valores válidos. Senhas são
limpas antes do envio, ao cancelar/fechar e ao terminar a operação, inclusive
em falhas. Não são gravadas em HTML, URLs, logs, localStorage ou sessionStorage.
O navegador ainda pode oferecer seu próprio gerenciador de senhas; o código
da aplicação não salva credenciais no storage.

O botão Editar da própria conta é desabilitado com explicação textual.
O contrato atual da API recusa **toda edição da própria conta**, inclusive
username, além da proibição de alterar o próprio papel (RF25). A interface
preserva esse comportamento. UUID e associações permanecem sob controle do
servidor; não há controles para password_hash, id, status, reset ou reativação.

Desativar abre um diálogo que identifica a conta e avisa sobre perda de
acesso, revogação das sessões e preservação do histórico. O foco inicial é
Cancelar. Cancelamento ou Escape antes do envio não efetuam requisição.
INACTIVE tem a ação desabilitada; se os dados ficarem desatualizados, o
conflito real da API é tratado. A regra do último ADMIN, a revogação e a
auditoria continuam exclusivamente no back-end, sem contagem de admins ou
criação de eventos pelo JavaScript. Autodesativação permitida pelo servidor
conduz ao login após a sessão se tornar inválida.

Após sucesso, o diálogo fecha e a listagem é recarregada na página 1,
preservando filtros e tamanho. Um registro pode não aparecer se não atender
aos filtros; a mensagem confirma a operação independentemente desse recorte.
O link Consultar histórico de auditoria permite verificar os eventos reais
em /app/audit-logs, que continua sem ações de alteração/exclusão.

### Requisições e falhas

Todas as três mutações enviam X-CSRF-Token da sessão em memória e JSON pelos
componentes existentes de web.js. O navegador fornece Origin, e fetch usa
credentials: same-origin. Não há JWT, CORS, endpoint, dependência, modelo ou
migration novos. O módulo user-management.js é carregado somente na página
de Users após /auth/me; recebe callbacks de escrita, atualização e tratamento
de autenticação. Não duplica fetch, armazenamento de CSRF ou autenticação.
O fragmento user-dialogs.html, o CSS e os diálogos nativos reutilizam o
estilo da interface; dados de contas são inseridos por textContent/value.

Enquanto uma mutação está pendente, envios repetidos, cancelamento, Escape,
controles da listagem e logout são bloqueados; aria-busy e indicação de
carregamento sinalizam o estado. Não há retry automático de escrita.

- 401: fecha/limpa formulários e conteúdo da listagem e conduz ao login.
- 403: fecha o formulário, informa negação e reconsulta a identidade; uma
  remoção do papel ADMIN esconde os controles administrativos.
- 409: mensagens conhecidas para username duplicado, último ADMIN e conta
  já inativa; outros conflitos recebem mensagem genérica.
- 422: solicita correção de campos, sem eco do payload.
- 404: orienta atualizar a listagem do alvo inexistente.
- 500, timeout ou rede: não confirma sucesso; orienta fechar e consultar o
  estado atual antes de repetir. Uma resposta perdida pode ocorrer após o
  servidor confirmar a operação; o cliente não promete execução exatamente
  uma vez. A proteção de duplicação cobre envios locais simultâneos, sem
  introduzir chaves de idempotência ou alterar o contrato da API.

Somente mensagens fixas/conhecidas de erro são exibidas, nunca detalhes
arbitrários recebidos da API. A CSP e as proteções de cookie/CSRF anteriores
continuam ativas. API e servidor seguem responsáveis por todas as decisões
de autorização e regras de negócio, independentemente do estado visual.

### Requisitos e validação

RF19.1/RF30 são integrados pelos formulários, RF19.2 pela confirmação e
desativação, RF25 pelo bloqueio visual e validação existente no servidor,
RF31 pelos conflitos retornados pelo back-end e RF15.1/RF26 pela auditoria
atômica já implementada. RF03/RNF02 são preservados neste escopo, sem
declarar concluída a matriz inteira do MVP. spec.md e ADR não são alterados.

Execute na pasta backend, com Chromium instalado conforme as instruções
anteriores:

```powershell
python -m pytest tests/test_web_user_management.py tests/test_web.py -q
python -m pytest --cov=app --cov-report=term-missing --cov-fail-under=70 -q
```

As suítes compartilham uma única fixture Chromium de sessão em conftest.py;
as verificações anteriores foram preservadas. Novos testes AAA cobrem
cadastro ADMIN/ANALYST, confirmação/limpeza de senha, dados inválidos,
duplicação, edição de username/papel, UUID/hash preservados, auditoria única,
própria conta, último ADMIN, confirmação/cancelamento, sessões revogadas,
CSRF nas três mutações, alteração de papel durante o formulário, erros,
rede, atualização com filtros, envios duplicados, XSS, teclado e dimensões
desktop/móvel. Screenshots de layout com dados sintéticos são criados no
diretório temporário do pytest, sem senha preenchida ou tokens visíveis.
Integração usa somente mini_soc_test, schemas isolados e rollback; nenhum
dado de desenvolvimento é alterado. Cobertura pytest-cov refere-se a Python,
não a instruções JS/CSS nem conformidade integral de acessibilidade.

Resultado desta entrega: **320 testes aprovados**, com 34 novos cenários e
as 286 regressões anteriores preservadas. Cobertura Python geral de app:
**98,56%** (763 instruções, 11 não cobertas), acima da meta de 70%.

Roteiro manual em ambiente de validação com contas de teste:

1. Como ADMIN, abrir /app/users e Novo usuário. Navegar por Tab/Shift+Tab,
   preencher cada papel, conferir divergência de senha e concluir cadastro.
2. Editar username e papel de outra conta. Conferir retorno à listagem,
   filtros preservados, própria edição indisponível e auditoria real única.
3. Abrir Desativar, ler o aviso e cancelar por botão/Escape. Reabrir e
   confirmar para uma conta de teste; verificar INACTIVE e perda de acesso
   da sessão dessa conta. Verificar conflito do último ADMIN em ambiente
   controlado, sem duplicar a regra na tela.
4. Simular erros de rede/API no DevTools, conferir feedback e ausência de
   reenvio automático. Validar que logout e escrita continuam com CSRF.
5. Repetir em 1440x1000 e 390x844: foco nos diálogos, retorno ao acionador,
   rolagem interna, mensagens e navegação por leitor de tela. ANALYST deve
   continuar sem a página/ações administrativas.

Revisão manual com leitor de tela e proxy/TLS real continua pendente. Não
há reset, reativação, exclusão física ou edição de auditoria. Esta entrega
depende de #26 -> #24 -> #22 -> #19 e da promoção em #20, sem merge automático.

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
# Validação das Detection Rules - Issue #35

Esta entrega complementa o motor existente, sem alterar os parâmetros da
DR01, DR02 ou DR03 definidos na seção 8 de `spec.md`.

`Log` exige `occurred_at` com offset explícito, seja datetime ou texto ISO 8601.
Entradas sem fuso geram ValueError; nenhum fuso é inferido. O instante fornecido
é preservado e a DR03 o converte para America/Sao_Paulo ao avaliar expediente.
Essa correção atende ao contrato já aprovado da seção 3.1, sem nova regra funcional.

`DetectionEngine.register_rule(rule, evaluator)` registra uma extensão interna
de desenvolvimento: o avaliador recebe Log e retorna Alert ou None. A regra
deve ter metadados válidos e o avaliador deve produzir Alerts coerentes com ela.
Não substitui regras existentes e não permite cadastrar regras pela aplicação.
Os avaliadores devem ser registrados antes dos lotes. A proposta de arquitetura
e seus limites estão em `docs/adr/02-extensao-detection-rules.md`, ainda sob revisão.

O histórico das regras iniciais é atualizado independentemente da ativação,
preservando o comportamento anterior. Somente avaliadores ativos são chamados;
AUTH_SUCCESS encerra o histórico DR02 mesmo quando a regra está inativa.

Rastreabilidade:

| Referência | Evidência e limite |
|---|---|
| RF07 / seção 8 | Testes dos limites de 120/300 s, isolamento, UTC e expediente. |
| RF08 / RF09 | Alerts em memória com origem, evidências, NEW e Severity das regras. Persistência pendente. |
| RF23 | Avaliadores inativos não executam; três regras iniciais cobertas. |
| RF18 / RF24 | Troca em memória e preservação dos Alerts anteriores; API, autorização, auditoria e persistência pendentes. |
| Seção 8.1 | Deduplicação de sequências DR01, consumo DR02 e histórico na reativação. |
| Seção 8.2 | Ordenação/desempate e rejeição de eventos antigos ou iguais em lote posterior. |
| RNF08 | Registro de avaliador adicional preservando resultados de DR01-DR03. ADR-002 proposto. |
| CQ01 | Gate específico de pelo menos 80% para o motor. |
| RF06 / seção 3.1 | Validação de fuso no objeto Log; importação completa e Assets persistidos pendentes. |

Dentro de `backend`, com as dependências de desenvolvimento instaladas:

```powershell
python -m pytest --noconftest tests/test_detection_engine.py tests/test_detection_validation.py --cov=app.detection_engine --cov-branch --cov-report=term-missing --cov-fail-under=80 -q
```

`--noconftest` restringe esta execução aos testes puros, sem carregar fixtures
de banco. Nenhum dos dois arquivos usa PostgreSQL ou arquivos de ambiente.
A execução acima não substitui a suíte completa ou sua meta geral de cobertura.

Verificação local desta entrega no Python 3.14.10: 46 testes aprovados
(9 anteriores e 37 novos), 97,27% de cobertura combinada de linhas/ramificações
do motor, com pytest 9.1.1 e pytest-cov 7.1.0 em ambiente isolado de ferramentas.
Também passaram 30 regressões sem banco (health, senhas, proteção do bootstrap,
configuração e validação de papéis). As dependências declaradas foram instaladas
sem alteração dos requirements; o ambiente de ferramentas inclui tzdata.
A execução anterior em Python 3.12.14 passou os mesmos 46 testes, com 97,51%.
A diferença de cobertura decorre da medição no interpretador utilizado.
A CI, a suíte completa com PostgreSQL e a revisão da Pessoa 1 permanecem pendentes.
Este clone não possui .env.test; não foi utilizado banco de desenvolvimento.

Persistem como pendentes: RF21 (rejeição parcial da importação), RF22 (unicidade
persistente de event_id), RNF03 (recuperação após reinício), RF15.1 (auditoria),
integração com Assets/Logs/Alerts e desempenho RNF05/RNF06. O estado e os IDs
locais do motor não devem ser considerados contratos persistentes do sistema.
