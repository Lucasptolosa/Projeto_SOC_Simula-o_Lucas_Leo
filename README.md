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

Esta entrega não adiciona login, autorização, cadastro público, endpoints
administrativos, auditoria administrativa nem regra do último ADMIN.
Esses comportamentos permanecem nas respectivas Issues. A instalação local
real não cria contas automaticamente durante migrations ou testes.

## Regras de Investigation e False Positive — Issue #33

`backend/app/investigations/rules.py` contém um núcleo puro de validação,
sem banco, dependências externas, entidades ORM, rotas ou emissão de Audit
Logs. Não importa Detection Engine/Alerts nem o módulo de Incidents.

Na preparação, a Issue #12 da Pessoa 2 permanecia aberta e o Alert existente
em app/detection_engine.py usava status textual. Não foi encontrado AlertStatus
nas branches remotas verificadas. Esta entrega usa o contrato de valores
exatos NEW, IN_REVIEW, DISMISSED e ESCALATED, **sem criar outra enumeração
ou entidade Alert** e sem modificar esse código.

| Função | Origem exigida | Resultado |
|---|---|---|
| validate_start_investigation(current_status, *, actor_role) | NEW | IN_REVIEW. |
| validate_false_positive(current_status, justification=None, *, actor_role) | IN_REVIEW | DISMISSED, com justificativa textual válida. |
| validate_escalation_eligibility(current_status, *, actor_role) | IN_REVIEW | None: apenas precondição de escalonamento. |

Todas exigem actor_role com valor ANALYST, sem papel padrão/implícito. ADMIN
e outros valores são recusados. O futuro serviço deve obter esse papel do
User autenticado e atualizado no servidor; o parâmetro não deve vir do cliente.
Essa defesa de domínio não substitui autenticação, User ACTIVE e RBAC da API.

Exemplo a partir da pasta backend:

```python
from app.investigations.rules import (
    validate_start_investigation, validate_false_positive,
    validate_escalation_eligibility,
)

review = validate_start_investigation("NEW", actor_role="ANALYST")
dismissed = validate_false_positive(
    review, "Atividade legítima confirmada.\nEvidência revisada.", actor_role="ANALYST",
)
validate_escalation_eligibility("IN_REVIEW", actor_role="ANALYST")
```

O último exemplo não altera estado nem retorna ESCALATED. Só verifica uma
precondição; o futuro serviço não poderá persistir esse estado sem criar
exatamente um Incident associado na mesma transação (RF11). Nenhuma função
desta entrega oferece uma mudança efetiva para ESCALATED.

Os valores de estado/papel devem ser strings exatas. StrEnum é compatível
por ser uma string; se o contrato futuro de Alerts usar outro Enum, o
adaptador deverá passar seu value textual. Não há coerção de números,
remoção de espaços ou conversão de caixa dos estados/papéis. Essa fronteira
permite reutilizar o tipo integrado pela Pessoa 2 sem reconciliar um segundo
tipo de produção criado por esta Issue.

DISMISSED e ESCALATED são terminais. Repetir o início, descartar NEW,
reiniciar um Alert encerrado ou tentar uma origem inadequada à decisão
gera InvestigationRuleError, derivado de ValueError. A interface por ações
fixa os únicos destinos disponíveis nesta entrega, recusando reversões e
transições não previstas sem introduzir um workflow genérico.

False Positive exige justificativa str não vazia. Ausência, None, string
vazia, whitespace ASCII/Unicode e tipos não textuais são recusados. strip()
é usado somente para testar se há conteúdo: o texto original não é
reescrito, truncado ou armazenado. Um caractere textual, acentos, múltiplas
linhas e espaços ao redor são aceitos. Não foi criado limite máximo ausente
da spec; caracteres que Python não considera whitespace não recebem política
adicional nesta entrega.

Mensagens de erro são fixas, sem repetir estado, papel, justificativa ou
observações recebidos. A autorização do papel é verificada antes do estado.
As funções não recebem uma entidade para modificar e não registram logs;
retornar um destino válido ainda não aplica qualquer mudança ao Alert.

### Integração futura

Quando a persistência de Alerts for integrada, o serviço deverá:

1. Autenticar o User e verificar estado ACTIVE.
2. Autorizar somente ANALYST usando get_current_user/require_roles, sem
   herança implícita de permissões para ADMIN.
3. Recuperar o Alert no PostgreSQL dentro da Session/transação apropriada,
   definindo o controle de concorrência antes de aceitar gravações.
4. Validar o estado atual e a decisão com as funções deste módulo, usando
   o papel obtido do servidor.
5. Registrar a Investigation ou a justificativa original validada.
6. Armazenar analista e horário da operação.
7. Aplicar o destino retornado quando permitido. Escalonamento exige também
   criar exatamente um Incident associado, sem gravação isolada de ESCALATED.
8. Acrescentar a auditoria exigida pelo fluxo na mesma Session.
9. Confirmar tudo atomicamente; falhas deverão reverter todas as gravações.

Autenticação/RBAC estão na main remota e auditoria nas branches administrativas;
esta base empilhada não precisa importá-los. append_audit adiciona eventos
à Session sem commit próprio, mas o AuditLog atual tem old_role/new_role
específicos de papéis. RF15.2 precisará representar os estados anterior/novo
de Alert em uma futura integração, sem reutilizar esses campos para status.
RF15.2 exige eventos para descarte/escalonamento bem-sucedidos; esta Issue
não amplia a política de auditoria nem grava eventos por conta própria.

| Referência | Entrega e limite |
|---|---|
| RF10 | Validação de NEW -> IN_REVIEW; observações, analista, horário e persistência pendentes. |
| RF20 | Validação de IN_REVIEW -> DISMISSED e justificativa; armazenamento/fluxo persistido pendentes. |
| RF32 / seção 7 | Erro de domínio e dados preservados; resposta HTTP/rollback do serviço pendentes. |
| RN02 | Exige papel ANALYST no núcleo; autenticação e papel confiável dependem da futura camada de servidor. |
| RF11 | Somente elegibilidade em IN_REVIEW; criação de Incident e mudança atômica para ESCALATED não implementadas. |
| RF15.2 | Auditoria persistida não implementada. |

### Testes e cobertura

Os testes em tests/test_investigation_rules.py seguem AAA e não solicitam
fixtures de PostgreSQL. Cobrem estados válidos/terminais, repetição/reversões,
papéis/status inválidos, omissão de papel, justificativa ausente/vazia/
whitespace/não textual, textos preservados, StrEnum, sigilo de erros e ausência
de mutação. Um subprocesso Python isolado (-I -S), sem pacotes externos e
com acesso a arquivos/rede bloqueado após importação, executa as três funções.

Validação local: **178 testes aprovados** (112 novos e 66 anteriores),
**97,64% de cobertura geral** e **100% no módulo de regras**. A execução
isolada dos 112 testes também atingiu 100% de linhas e ramificações.

Na pasta backend:

```powershell
python -m pytest tests/test_investigation_rules.py --cov=app.investigations.rules --cov-branch --cov-report=term-missing --cov-fail-under=80 -q
python -m pytest --cov=app --cov-report=term-missing --cov-fail-under=70 -q
python -m coverage report --include=app/investigations/rules.py --fail-under=80
```

A CI desta branch exige também 80% específico, mantendo os 70% gerais e todos
os testes anteriores intactos. As integrações anteriores continuam restritas
a mini_soc_test, com schemas isolados e rollback. Esta entrega usa
feat/regras-investigacoes sobre ci/testes-automatizados enquanto #30 estiver
aberto, independentemente do PR #32. Não modifica spec/ADR, dependências,
Assets, Logs, Detection Rules, Alerts ou PRs anteriores. A futura integração
transacional permanece condicionada ao contrato persistido da Pessoa 2.

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
