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
