Repositório destinado ao projeto de "Mini SOC educacional" relacionado à aula de Modelagem de Sistemas, feitos por Lucas e Leonardo


## Desenvolvimento local do back-end

O back-end do Mini SOC utiliza Python e FastAPI, conforme
a arquitetura técnica aprovada no ADR-001.

### Pré-requisitos

- Python 3 (ambiente de desenvolvimento validado com Python 3.14.8).
- Git.
- Terminal para execução dos comandos.

### 1. Clonar o repositório

Clone o repositório pelo Git e acesse sua pasta.

### 2. Criar o ambiente virtual

Na raiz do repositório, no Windows:

```powershell
py -m venv .venv
```

### 3. Ativar o ambiente virtual

No PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 4. Instalar as dependências

Para desenvolvimento e testes:

```powershell
python -m pip install -r backend/requirements-dev.txt
```

Para instalar somente as dependências de execução:

```powershell
python -m pip install -r backend/requirements.txt
```

### 5. Executar a aplicação

A partir da raiz do repositório:

```powershell
python -m uvicorn app.main:app --app-dir backend --reload
```

A aplicação estará disponível em:

- API: http://127.0.0.1:8000
- Health check: http://127.0.0.1:8000/health
- Documentação: http://127.0.0.1:8000/docs

O endpoint GET /health deverá retornar HTTP 200:

```json
{
  "status": "ok"
}
```

### 6. Executar os testes

Em outro terminal, a partir da raiz do repositório:

```powershell
cd backend
python -m pytest -q
```

### Estado atual da implementação

Esta versão inicial disponibiliza somente a estrutura da API,
o endpoint de health check e seu teste automatizado.

A integração com PostgreSQL, autenticação e funcionalidades
de negócio será implementada em entregas posteriores.

# Mini SOC

Sistema acadêmico de monitoramento de segurança, desenvolvido para receber logs simulados, aplicar regras de detecção, gerar alertas e permitir a investigação e o tratamento de incidentes.

## Tecnologias

- Python 3.14
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

Na raiz do repositório, crie e ative o ambiente virtual:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Instale as dependências:

```powershell
python -m pip install -r backend/requirements-dev.txt
```

## Configuração do PostgreSQL

No PostgreSQL, crie:

- Uma Role chamada `mini_soc_app`, com permissão de login, senha própria e sem privilégios de superusuário.
- Um banco chamado `mini_soc_dev`, com `mini_soc_app` como proprietário.
- Um banco chamado `mini_soc_test`, com `mini_soc_app` como proprietário.

O banco `mini_soc_dev` será utilizado para desenvolvimento, enquanto `mini_soc_test` será utilizado nos testes automatizados.

## Variáveis de ambiente

Dentro de `backend/`, crie os arquivos `.env` e `.env.test`, utilizando `.env.example` como referência.

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
