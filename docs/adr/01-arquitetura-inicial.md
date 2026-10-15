
# ADR-001 — Arquitetura Técnica Inicial do Mini SOC

## 1. Decisão

### 1.1. Stack tecnológica

| Componente | Tecnologia |
|---|---|
| Linguagem do back-end | Python |
| Framework back-end | FastAPI |
| Front-end | HTML, CSS, JavaScript e Jinja2 |
| Banco de dados | PostgreSQL |
| ORM | SQLAlchemy |
| Migrations | Alembic |
| Testes automatizados | pytest |

### 1.2. Arquitetura de software

O sistema adotará uma arquitetura de **monólito modular**.

O back-end será desenvolvido como uma única aplicação, organizada internamente em módulos com responsabilidades definidas.

A organização seguirá a separação de responsabilidades entre:

- **Camada de API:** recebimento de requisições HTTP, validação de entradas e construção de respostas.
- **Camada de serviços:** implementação e coordenação das regras de negócio.
- **Camada de persistência:** acesso e manipulação dos dados armazenados no banco.

A estrutura detalhada dos módulos e diretórios será definida no planejamento técnico.

## 2. Justificativas

- **Python e FastAPI:** facilitam o desenvolvimento de APIs HTTP, a implementação das regras de negócio e os testes automatizados.
- **PostgreSQL:** oferece persistência relacional, integridade dos dados e suporte a transações, necessários para manter a consistência das operações do sistema.
- **SQLAlchemy e Alembic:** permitem realizar o mapeamento objeto-relacional e gerenciar a evolução do esquema do banco de dados.
- **HTML, CSS, JavaScript e Jinja2:** permitem construir a interface web sem a necessidade de uma aplicação front-end independente.
- **Monólito modular:** permite separar responsabilidades e organizar os componentes sem introduzir a complexidade operacional de uma arquitetura distribuída, sendo adequado ao escopo do MVP e ao tamanho da equipe.

## 3. Consequências

### Benefícios

- Menor complexidade de desenvolvimento e implantação.
- Separação de responsabilidades entre os componentes.
- Facilidade de manutenção e testes automatizados.
- Persistência relacional com suporte a transações.
- Possibilidade de evolução incremental do sistema.

### Limitações e responsabilidades

- O back-end será implantado como uma única unidade.
- Os módulos compartilharão o mesmo processo e precisarão manter limites claros de responsabilidade.
- Será necessário controlar as dependências entre módulos para evitar acoplamento excessivo.
