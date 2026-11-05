# Mini SOC

Protótipo acadêmico de um Security Operations Center para estudar monitoramento,
detecção e tratamento de eventos de segurança em ambientes corporativos. O
modelo funcional relaciona Logs, Detection Rules, Alerts, Investigations e
Incidents, com controles de acesso e preservação de evidências.

O objetivo é apoiar a triagem e o tratamento de incidentes por Security Analysts
e a administração do ambiente por Administrators. O escopo completo, inclusive
os comportamentos sem interface implementada, está na [especificação](spec.md).

## Tecnologias

- Python 3.14, FastAPI e Uvicorn.
- PostgreSQL; a CI utiliza PostgreSQL 17.
- SQLAlchemy, Psycopg e Alembic.
- HTML, CSS, JavaScript e Jinja2, sem etapa de build de front-end.
- pytest, pytest-cov e Playwright/Chromium para validação automatizada.

As versões das dependências estão em [requirements.txt](backend/requirements.txt)
e [requirements-dev.txt](backend/requirements-dev.txt).

## Arquitetura e organização

O sistema é um monólito modular. A API recebe e valida requisições, os serviços
coordenam regras e transações, e os repositórios acessam o banco de dados.

```text
backend/
  app/
    auth/              autenticação, sessões e RBAC
    users/             administração de contas
    assets/            administração de ativos
    logs/              importação persistente
    detection/         catálogo, estado e Alerts persistidos
    audit/             registros e consultas de auditoria
    incidents/         escalonamento, persistência e regras de Incident
    investigations/    investigações, observações e falso positivo
    web/               páginas, templates e recursos estáticos
    core/              configuração, paginação e erros
    db/                Base, Engine e fábrica de sessões
    detection_engine.py
  migrations/          revisões Alembic
  tests/               testes unitários, de integração e de navegador
docs/                  documentação técnica e ADRs
.github/               workflow e preparação do ambiente de CI
```

O [guia técnico dos componentes](docs/arquitetura-aplicacao.md) descreve as
fronteiras entre módulos, transações e mecanismos de segurança.

## Pré-requisitos

- Python 3.14 e Git.
- PostgreSQL disponível, com permissão administrativa para a preparação inicial.
- Terminal interativo para criar a conta Administrator.
- Chromium instalado pelo Playwright para executar os testes de navegador.

Os comandos de instalação abaixo usam PowerShell. No Linux, a ativação do
ambiente virtual usa `source .venv/bin/activate`; os comandos Python são comuns.

## Instalação e configuração

Na pasta em que o projeto será instalado:

```powershell
git clone https://github.com/Lucasptolosa/Projeto_SOC_Simula-o_Lucas_Leo.git
cd Projeto_SOC_Simula-o_Lucas_Leo
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements-dev.txt
```

Para instalar apenas as dependências de execução, utilize
`python -m pip install -r backend/requirements.txt`.

### Bancos e role de aplicação

Em uma sessão administrativa do `psql`, crie somente recursos inexistentes:

```sql
CREATE ROLE mini_soc_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
\password mini_soc_app
CREATE DATABASE mini_soc_dev OWNER TO mini_soc_app;
CREATE DATABASE mini_soc_test OWNER TO mini_soc_app;
```

`\password` solicita a senha interativamente. Para recursos já existentes,
confira propriedade e permissões; não exclua bancos para repetir a instalação.
A role de aplicação precisa criar schemas e objetos temporários em
`mini_soc_test`, sem privilégios administrativos sobre o servidor.

### Variáveis de ambiente

Na raiz do repositório, copie o [exemplo de configuração](backend/.env.example)
sem sobrescrever arquivos locais existentes:

```powershell
if (-not (Test-Path -LiteralPath backend/.env)) { Copy-Item backend/.env.example backend/.env }
if (-not (Test-Path -LiteralPath backend/.env.test)) { Copy-Item backend/.env.example backend/.env.test }
```

Configure `backend/.env` para desenvolvimento:

```dotenv
DB_HOST=localhost
DB_PORT=5432
DB_NAME=mini_soc_dev
DB_USER=mini_soc_app
DB_PASSWORD=SUBSTITUIR_PELA_SENHA
AUTH_ORIGIN=http://127.0.0.1:8000
AUTH_COOKIE_SECURE=false
AUTH_SESSION_SECONDS=28800
```

Substitua o valor de `DB_PASSWORD` pela senha da role local. Em
`backend/.env.test`, defina **`DB_NAME=mini_soc_test`** e as credenciais de teste.
Não versione dotenv, senhas ou tokens.

Variáveis do processo têm precedência sobre os arquivos dotenv. Antes dos
testes, confira se `DB_*` exportadas no terminal apontam para `mini_soc_test`.
As fixtures validam o nome configurado e `SELECT current_database()` antes de
gravar dados. A conexão tem timeout de cinco segundos.

`AUTH_ORIGIN` deve corresponder ao endereço exato usado pelo navegador,
incluindo esquema, host e porta. Cookie sem Secure é permitido somente em HTTP
loopback (`localhost`, `127.0.0.1` ou `::1`). Em HTTPS, configure a origem real e
`AUTH_COOKIE_SECURE=true`. A validade absoluta da sessão é configurável entre
1 e 86.400 segundos; o padrão é 28.800 segundos.

## Banco de dados e migrations

Com o ambiente virtual ativo, execute a partir de `backend/`:

```powershell
cd backend
python -m alembic current
python -m alembic heads
python -m alembic upgrade head
```

Confira o banco de destino em `.env` e revise as
[migrations](backend/migrations/versions) antes do upgrade. Elas criam a
estrutura de Users, sessões, auditoria, Assets, Logs, catálogo de regras,
estado de detecção, Alerts, evidências, investigações, observações e Incidents,
sem criar contas.
O Alembic usa `Settings` e a `Base.metadata` compartilhada; a URL genérica de
`alembic.ini` não define a conexão. Geração offline de SQL não é suportada.

Não recrie tabelas existentes nem edite revisões já aplicadas em ambientes
persistentes. Uma revisão registrada como aplicada não é executada novamente
por `upgrade head`; divergências de estrutura exigem análise e migration
aditiva. Reversões com perda de dados não são procedimentos de manutenção.

A revisão `0006_detection_persistence` sucede `0005_create_logs` e cria
`detection_rules`, `detection_state`, `alerts` e `alert_logs`. Inicializa DR01-DR03
ACTIVE, com Severity fixa, e estado vazio versionado. Deve estar aplicada antes
de servir a aplicação. Não processa Logs existentes nem os utiliza para iniciar
sequências; reenviar esses Logs continua sendo duplicação. Recuperação e backup
devem preservar o conjunto de tabelas de um mesmo ponto confirmado. Não execute
downgrade destrutivo ou exclusão de histórico para reaplicar a revisão.

### Administrator inicial

Após preparar a estrutura, execute em um terminal interativo, dentro de
`backend/`:

```powershell
python -m app.users.create_admin
```

O comando solicita nome e senha com confirmação, sem eco da senha. Não aceita
argumentos ou entrada por pipe e não possui credenciais padrão. Cria uma conta
`ADMIN ACTIVE` somente quando não existe nenhum User, em uma transação com
serialização da instalação. Não redefine contas nem serve para recuperação de
senha. Restrinja o acesso ao terminal e às credenciais do PostgreSQL.

## Execução do backend e acesso à interface

Dentro de `backend/`, com o ambiente virtual ativo:

```powershell
python -m uvicorn app.main:app --reload
```

- [Login](http://127.0.0.1:8000/login).
- [Área autenticada](http://127.0.0.1:8000/app).
- [Documentação interativa da API](http://127.0.0.1:8000/docs).
- [Health check](http://127.0.0.1:8000/health): verifica a API, sem testar PostgreSQL.

O endereço de acesso deve coincidir com `AUTH_ORIGIN`. `--reload` é destinado
ao desenvolvimento local. A interface utiliza recursos locais e dispensa Node.

## Funcionalidades disponíveis

| Componente | Interface e responsabilidade |
|---|---|
| Autenticação | `POST /auth/login`, `GET /auth/me`, `POST /auth/logout`; sessões persistidas, expiração, revogação e CSRF. |
| Users | ADMIN cadastra, altera e desativa contas; `GET /users` fornece paginação e filtros de papel/estado. A interface está em `/app/users`. |
| Assets | ADMIN usa `POST /assets`, `PATCH /assets/{id}` e `POST /assets/{id}/deactivate`; alterações efetivas geram auditoria atômica. |
| Auditoria | ADMIN consulta `GET /audit-logs` e `/app/audit-logs`, em ordem recente primeiro. Não há operações de edição ou exclusão. |
| Logs | ADMIN envia lotes JSON a `POST /logs/import`; validação e persistência com rejeição individual e unicidade de `event_id`. |
| Detecção persistente | A importação avalia DR01-DR03; grava Alerts, evidências e estado transacional, com continuidade entre lotes e reinícios. |
| Administração de regras | ADMIN usa `PATCH /detection-rules/{rule_id}` com `status` ACTIVE/INACTIVE; alteração efetiva e auditoria são atômicas. |
| Incidents | ANALYST consulta lista e detalhe em `/app/incidents`, aplica filtros e executa tratamento, contenção e resolução pelas APIs existentes. [Contratos e regras](docs/regras-transicao-incidentes.md). |
| Investigations | ANALYST inicia investigação, registra e consulta observações e descarta falsos positivos, com persistência e auditoria atômicas. [Contratos e API](docs/regras-investigacoes.md). |

Consulta geral de Logs e Alerts e Dashboard
não são expostos pela aplicação.
Gerar Alerts na importação não concede sua consulta ao ADMIN.

A revisão `0007_create_investigations` sucede a persistência de detecção e cria
`investigations` e `investigation_observations`, com vínculos aos Alerts e Users
existentes. Acrescenta `old_status/new_status` aos Audit Logs, sem reutilizar
campos de papel ou modificar registros anteriores. Consulte a
[documentação de Investigations](docs/regras-investigacoes.md) para rotas,
paginação e regras de transação.

`POST /investigations/{id}/escalate` cria um Incident e altera o Alert para
ESCALATED com auditoria na mesma transação. O Incident herda a Severity do
Alert e registra o solicitante como responsável; `GET /incidents/{id}` recupera
o registro. Ambas as operações exigem ANALYST ativo. A revisão
`0008_create_incidents` sucede a 0007 e garante um Incident por Alert no banco.

`POST /incidents/{id}/transitions` recebe `target_status` e o texto pertinente:
`containment_description` para CONTAINED ou `resolution_conclusion` para RESOLVED.
Somente as quatro transições da seção 9 da spec são permitidas. A contenção
e a resolução preservam texto, autor e instante, além da abertura original.
A migration `0009_incident_treatment` acrescenta esses campos sem alterar
registros anteriores. A mudança e seu Audit Log são confirmados na mesma
transação, sem alterar o Alert ESCALATED ou suas evidências.

A página `/app` exibe a identidade autenticada; as páginas administrativas são
exclusivas de ADMIN. ADMIN não herda as permissões de ANALYST. Não há cadastro
público, reset de senha ou reativação de contas pela API.

ANALYST acessa `/app/incidents` pelo menu ou pela página inicial. A lista mantém
a prioridade do backend e possui filtros e paginação. O detalhe permite as ações
correspondentes ao estado atual, com CSRF, atualização após confirmação e
tratamento de conflitos. Os contratos de datas e formulários estão no
[guia de Incidents](docs/regras-transicao-incidentes.md#interface-web).

Os contratos completos, incluindo limite de 1.024 bytes UTF-8 para `event_id`,
Assets inativos, rejeições e regras de Users/Assets, estão na [spec](spec.md).

### Importação e detecção

`POST /logs/import` mantém `accepted`, `rejected` e `rejections` como resultado
da validação e persistência. Somente Logs novos e válidos entram no motor.
O bloco `detection` separa o resultado da avaliação:

```json
{
  "accepted": 2,
  "rejected": 0,
  "rejections": [],
  "detection": {
    "evaluated": 1,
    "rejected": 1,
    "rejections": [
      {"position": 2, "reason": "out_of_order", "detail": "Evento fora de ordem para detecção."}
    ],
    "alerts_created": 0
  }
}
```

O exemplo representa dois Logs aceitos na ingestão, com um deles fora de ordem
para detecção. Esse Log permanece armazenado e não altera sequências ou gera
Alert. `detection.evaluated + detection.rejected` equivale a `accepted`.
Posições começam em 1 na entrada original; cada lote é avaliado por
`occurred_at` e depois `event_id`. O estado confirmado antes do lote define os
limites temporais para eventos de lotes posteriores.

Cada Alert possui UUID, Status NEW, Severity da regra, instante do evento
acionador e vínculos ordenados aos Logs de evidência, protegidos por FKs.
Logs, Alerts, evidências e estado do motor são confirmados na mesma transação;
falha operacional ou de commit reverte o conjunto. Contagens de sucesso só são
retornadas após commit.

O módulo `app/detection` restaura uma instância do motor por transação a partir
de JSONB versionado. O bloqueio da linha única de estado precede a ingestão e
coordena lotes de diferentes processos; não há estado global mutável ou reset
silencioso para catálogo/estado inconsistente. A serialização limita o
paralelismo e o histórico pode crescer; testes funcionais não comprovam RNF06.
Os [contratos de integração](spec.md#312-integração-da-importação-com-detection-engine)
e o [guia dos componentes](docs/arquitetura-aplicacao.md) detalham ordenação,
deduplicação, recuperação e limites arquiteturais.

### Ativação e desativação de regras

`PATCH /detection-rules/DR01` recebe, por exemplo, `{"status":"INACTIVE"}`.
Exige ADMIN ativo, sessão, Origin e CSRF. A resposta HTTP 200 contém `id`,
`status` e `severity`; não permite editar identificador, parâmetros ou Severity.
Identificadores são DR01-DR03, sem conversão de caixa. Regra ausente retorna
404; corpo inválido ou com campos adicionais, 422 genérico. Proteções de
autenticação/autorização mantêm 401/403 e a resposta usa Cache-Control no-store.

Repetir o estado atual retorna a regra sem nova auditoria. Mudança efetiva
registra autor, ação ACTIVATED/DEACTIVATED, entidade DETECTION_RULE, identificador
e instante usando a auditoria existente, na mesma transação da regra. Falhas
revertem ambas. Não usa os campos old_role/new_role para registrar estado.

A operação revalida e bloqueia o autor, depois usa a linha de estado do motor
e bloqueia a regra, coordenando-se com a importação. Lotes posteriores ao commit
usam o novo estado. Não limpa históricos, altera Alerts anteriores ou dispara
detecção retroativa. Não cria tabelas, migrations, regras ou telas. Os contratos
estão na seção 3.3 da spec; o guia técnico descreve os bloqueios compartilhados.

## Testes automatizados

Configure `backend/.env.test` e mantenha PostgreSQL disponível. Na pasta
`backend/`, instale o navegador e execute a suíte:

```powershell
python -m playwright install chromium
python -m pytest --cov=app --cov-report=term-missing --cov-fail-under=70 --tb=no --show-capture=no -q
python -m coverage report --include=app/incidents/transitions.py --fail-under=80
python -m coverage report --include=app/investigations/rules.py --fail-under=80
```

No Linux, `python -m playwright install --with-deps chromium` também instala as
bibliotecas do navegador. Para execução sem relatório de cobertura, use
`python -m pytest -q`. Os testes seguem AAA (Arrange, Act, Assert).

Os testes de integração usam exclusivamente `mini_soc_test`, com tabelas
temporárias, schemas aleatórios e rollback. A verificação de concorrência de
Logs confirma dados apenas em seu schema exclusivo e remove esse schema ao
terminar. Nenhum teste deve usar `mini_soc_dev` ou dados de produção.

As metas são 70% geral e 80% nos módulos de Incidents e Investigations. CQ01
também exige 80% para Detection Rules; sua medição específica pode ser feita com:

```powershell
python -m pytest --noconftest tests/test_detection_engine.py tests/test_detection_validation.py --cov=app.detection_engine --cov-branch --cov-report=term-missing --cov-fail-under=80 -q
```

Os comandos específicos de domínio estão nas documentações vinculadas acima.
Os testes `tests/test_detection_persistence.py` e
`tests/test_detection_transactions.py` verificam evidências, janelas temporais,
ordenação, regras inativas, rollback, concorrência, continuidade em processos
independentes e migration sem avaliação retroativa de Logs.
A cobertura mede Python; não comprova cobertura de JavaScript/CSS, conformidade
integral de acessibilidade ou todos os requisitos não funcionais. Os testes web
usam Chromium com transporte ASGI/TestClient; validação de TLS/proxy real e de
leitor de tela requer verificações próprias, sem captura de credenciais.

### Integração contínua

O [workflow](.github/workflows/testes.yml) executa a suíte do checkout em Pull
Requests e pushes na main, com Python 3.14, PostgreSQL 17 descartável e Chromium
quando Playwright está instalado. Na aba Checks ou Actions, o job **Pytest e
cobertura** apresenta a etapa reprovada e o relatório de cobertura. Verde indica
sucesso das verificações executadas; vermelho indica falha; cancelado pode
indicar substituição por uma execução mais recente.

A CI cria somente `mini_soc_test` como banco de aplicação, usa role sem
privilégios administrativos e gera uma senha efêmera mascarada. O dotenv de
teste é temporário e removido ao final. Não são usados dados locais, produção
ou secrets pessoais. Os scripts de preparação são exclusivos do runner
hospedado e não devem ser executados contra o PostgreSQL local.

## Segurança e operação

- Senhas são armazenadas somente como hash Argon2id, com salt individual de
  pelo menos 16 bytes. O token de sessão é opaco; somente seu hash é persistido.
- Cookies são HttpOnly, SameSite=Strict e Secure por padrão. Escritas autenticadas
  exigem `Origin` e `X-CSRF-Token`; o login exige a origem configurada.
- Papéis e estado ACTIVE são verificados no servidor. Ocultar controles na
  interface não concede permissão. Nenhum token de sessão é armazenado em URL
  ou storage do navegador; CSRF permanece em memória.
- Não publique dotenv, senhas, tokens, hashes, dumps, cookies ou traces com dados
  sensíveis. Erros de credenciais e rejeições de Logs usam mensagens fixas.
- O bootstrap de CI substitui o trust inicial do serviço descartável por SCRAM,
  restringe a porta a loopback e verifica o banco real e os privilégios da role.
  O workflow usa `contents: read`, não persiste a credencial Git e não executa
  código de PR por `pull_request_target`.

### Logging do PostgreSQL

`hide_parameters` do SQLAlchemy não controla o log do processo PostgreSQL.
Falhas de constraint podem incluir a linha rejeitada em `DETAIL`. Na CI, o
[preparo do banco descartável](.github/scripts/prepare_test_database.py) aplica:

| Parâmetro | Valor |
|---|---|
| `log_error_verbosity` | `terse` |
| `log_min_error_statement` | `panic` |
| `log_statement` | `none` |
| `log_parameter_max_length` / `log_parameter_max_length_on_error` | `0` / `0` |
| `log_min_duration_statement` / `log_min_duration_sample` | `-1` / `-1` |
| `log_transaction_sample_rate` | `0` |

A [verificação de logging](.github/scripts/verify_test_logging.py) utiliza uma
violação CHECK com dados sintéticos: o controle DEFAULT deve revelar um
marcador, e a conexão da aplicação com o perfil restrito deve ocultar outro nos
logs reais. Marcadores são mascarados no Actions; logs brutos não são enviados
como artefatos. O teste falha se o controle positivo não comprovar acesso ao log.

`TERSE` omite detalhes úteis ao diagnóstico; `log_min_error_statement=panic`
restringe o SQL anexado, sem desativar o erro primário. Mensagens primárias,
extensões e outros destinos ainda podem expor valores. A política deve ser
avaliada pelo mantenedor para cada ambiente; não é instalada pela aplicação
nem pelas migrations e não garante sigilo de todo erro.

## Referências técnicas

- [Constituição — princípios de engenharia](constitution.md).
- [Orientações para agentes](AGENTS.md).
- [Especificação funcional e requisitos](spec.md).
- [Arquitetura dos componentes](docs/arquitetura-aplicacao.md).
- [ADR-001 — Arquitetura técnica](docs/adr/01-arquitetura-inicial.md).
- [ADR-002 — Extensão do Detection Engine](docs/adr/02-extensao-detection-rules.md).
- [ADR-003 — Estado transacional do Detection Engine](docs/adr/03-estado-transacional-detection-engine.md).
- [Incidents](docs/regras-transicao-incidentes.md) e [Investigations](docs/regras-investigacoes.md).
