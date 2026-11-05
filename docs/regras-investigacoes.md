# Regras de Investigations

O núcleo de domínio valida início de investigação, descarte como falso positivo e
elegibilidade para escalonamento conforme RF10, RF11, RF20, RF32,
RN02 e seção 7 da [spec](../spec.md). As funções são independentes de HTTP,
persistência e do Detection Engine.

## Organização e contratos

- [rules.py](../backend/app/investigations/rules.py): funções públicas e exceção
  `InvestigationRuleError`.
- [Testes](../backend/tests/test_investigation_rules.py): casos positivos,
  negativos, limites e isolamento do domínio, em padrão AAA.

```python
validate_start_investigation(current_status: str, *, actor_role: str) -> str
validate_false_positive(
    current_status: str,
    justification: str | None = None,
    *,
    actor_role: str,
) -> str
validate_escalation_eligibility(current_status: str, *, actor_role: str) -> None
```

| Função | Estado exigido | Retorno |
|---|---|---|
| `validate_start_investigation` | NEW | `"IN_REVIEW"` |
| `validate_false_positive` | IN_REVIEW | `"DISMISSED"` |
| `validate_escalation_eligibility` | IN_REVIEW | `None` |

Elegibilidade não cria Incident, não modifica Alert e não retorna ESCALATED.
Essa mudança depende da criação vinculada prevista no RF11.

## Validações e estados

Todas as funções exigem `actor_role="ANALYST"`. ADMIN e outros valores são
recusados. A verificação de papel ocorre antes da validação do estado.

Estados conhecidos são NEW, IN_REVIEW, DISMISSED e ESCALATED, com grafia exata,
sem conversão de caixa, remoção de espaços ou coerção de tipos. Como `StrEnum`
é string, pode ser usado diretamente; outros enums precisam de adaptação
explícita para seu valor textual. DISMISSED e ESCALATED são terminais.

Falso positivo exige justificativa do tipo string, não vazia e não composta
somente por whitespace reconhecido por `str.strip()`. A validação de
preenchimento não transforma nem armazena o texto. O módulo não define um
limite máximo de tamanho.

## Erros, segurança e integração

Violações do domínio lançam `InvestigationRuleError`, subclasse de `ValueError`, com
mensagens fixas e sem eco dos valores. As funções de domínio não fazem logging,
I/O, alteração de objetos ou acesso ao banco. O núcleo não autentica usuários e não confere
estado ACTIVE ou expiração de sessão.

O serviço consumidor deve usar identidade e papel obtidos no servidor,
validar a sessão e consultar o estado atual do Alert com controle de
concorrência. Não se deve aceitar `actor_role` como autorização fornecida
pelo cliente. Os estados retornados são resultados de validação, não prova
de persistência.

A camada persistente vincula analista, data/hora e observações à Investigation
e conserva as evidências originais. O descarte altera o Alert para DISMISSED e
registra justificativa, responsável, instante e auditoria na mesma transação.
`validate_escalation_eligibility` verifica a precondição do escalonamento; o
[serviço de Incidents](regras-transicao-incidentes.md#escalonamento-persistente)
coordena a criação vinculada e a alteração do Alert.

## Aplicação e persistência

- [models.py](../backend/app/investigations/models.py): `Investigation`, única por
  Alert, e `Observation`, com FKs RESTRICT para preservar vínculos e autoria.
- [schemas.py](../backend/app/investigations/schemas.py): entradas estritas e
  respostas públicas, sem modelos de User ou segredos.
- [repository.py](../backend/app/investigations/repository.py): recuperação,
  bloqueio do Alert e paginação de observações por `occurred_at ASC, id ASC`.
- [service.py](../backend/app/investigations/service.py): revalidação do autor,
  uso dos validadores e coordenação das gravações, sem commit próprio.
- [router.py](../backend/app/investigations/router.py): autenticação/RBAC,
  contratos HTTP e fronteira de commit/rollback.

As escritas bloqueiam primeiro o User e depois o Alert, recarregando os valores
persistidos antes da decisão. A constraint de unicidade impede uma segunda
Investigation para o mesmo Alert. Tentativas concorrentes de iniciar ou
descartar não substituem o autor, instante ou justificativa da decisão confirmada.

O descarte gera `ALERT_DISMISSED`, com entidade ALERT, autor, instante e
`old_status/new_status`. Os campos `old_role/new_role` continuam exclusivos de
papéis. A [migration 0007](../backend/migrations/versions/0007_create_investigations.py)
estende a auditoria de forma aditiva, com constraints para pares completos e
sem mistura de tipos de mudança. Registros anteriores permanecem preservados.

## API

Todas as rotas exigem ANALYST ativo. ADMIN não herda esse acesso. Escritas
exigem Origin e CSRF; o autor é obtido da sessão, sem exclusividade do analista
que iniciou a investigação.

| Método e rota | Entrada | Sucesso |
|---|---|---|
| POST /investigations | `alert_id` UUID | 201, investigação IN_REVIEW |
| GET /investigations/{id} | UUID | 200, investigação e Status atual |
| POST /investigations/{id}/observations | `content` | 201, observação persistida |
| GET /investigations/{id}/observations | `page`, `page_size` | 200, página de observações |
| POST /investigations/{id}/false-positive | `justification` | 200, investigação DISMISSED |
| POST /investigations/{id}/escalate | Corpo ausente ou JSON vazio | 201, Incident OPEN e vínculo com Alert |

A investigação retorna id, alert_id, analyst_id, started_at, status e os campos
justification, dismissed_by e dismissed_at quando preenchidos. A observação
retorna id, investigation_id, analyst_id, content e occurred_at.

Textos são strings não vazias nem compostas somente por whitespace, sem NUL e
representáveis em UTF-8. Valores válidos são preservados; não há limite máximo
adicional. Campos desconhecidos são rejeitados. Observações acrescentadas após
descarte não reabrem o Alert nem alteram a justificativa. Não há rotas para
editar ou excluir observações ou alterar Logs. Escalonamento exige IN_REVIEW,
cria um único Incident e grava ALERT_ESCALATED na mesma transação.

Paginação usa `page` de 1 a 10.000 e `page_size` de 1 a 100, com padrões 1 e 20.
Identidade inválida ou User inativo retorna 401; papel ou Origin/CSRF inválidos,
403; referência inexistente, 404; transição incompatível/repetida, 409; entrada
inválida, 422. Falha interna retorna erro genérico, com rollback e sem sucesso
parcial. Respostas protegidas usam Cache-Control no-store.

## Testes

Com dependências instaladas, a partir de `backend/`:

```powershell
python -m pytest tests/test_investigation_rules.py --cov=app.investigations.rules --cov-branch --cov-report=term-missing --cov-fail-under=80 -q
```

Esses testes não precisam de PostgreSQL. Para a suíte completa e metas de
cobertura geral e por módulo, utilize o [README](../README.md#testes-automatizados).

Os testes de [API e persistência](../backend/tests/test_investigations.py) e
[transações](../backend/tests/test_investigation_transactions.py) usam exclusivamente
mini_soc_test, com verificação de banco real, schemas isolados e rollback:

```powershell
python -m pytest tests/test_investigations.py tests/test_investigation_transactions.py -q
```

Cobrem autorização, textos inválidos, recuperação entre sessões, concorrência,
falhas de commit/auditoria, migration sobre auditoria existente e preservação
dos Logs/evidências. Descarte não cria Incident. A cobertura geral e os gates
dos módulos existentes permanecem definidos no README.
