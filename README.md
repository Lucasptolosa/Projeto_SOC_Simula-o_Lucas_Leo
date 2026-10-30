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
não aplica a matriz de permissões por papéis.

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
- RNF02/RF03: autenticação no servidor pronta; autorização por papel ainda
  será implementada em Issue própria.
- RF19.2: usuário inativo é bloqueado a cada acesso; endpoint de desativação
  e revogação definitiva de todas as sessões nessa operação ainda pendem.
- RNF09: tratamento técnico de falhas e sigilo; fluxos futuros de importação
  deverão reutilizar o tratamento e verificar seus próprios cenários.

Não há cadastro público, gerenciamento administrativo, UI de login,
limitação distribuída de tentativas ou renovação automática de sessão.
As integrações usam exclusivamente `mini_soc_test`, com schemas isolados e
rollback, incluindo comparação entre migration e metadata. Não comprovam
recuperação após reinício real do banco/aplicação. spec.md e ADR permanecem
como fonte de escopo e arquitetura.

Enquanto o PR #15 estiver aberto, o PR de autenticação usa
`codex/persistencia-users` como base. Após sua integração, deve ser
reconciliado com main e ter a base atualizada, preservando o histórico.

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
