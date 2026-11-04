# Regras de Investigations

O módulo valida início de investigação, descarte como falso positivo e
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

Violações lançam `InvestigationRuleError`, subclasse de `ValueError`, com
mensagens fixas e sem eco dos valores. Não há logging, I/O, alteração de
objetos ou acesso ao banco. O módulo não autentica usuários e não confere
estado ACTIVE ou expiração de sessão.

O serviço consumidor deve usar identidade e papel obtidos no servidor,
validar a sessão e consultar o estado atual do Alert com controle de
concorrência. Não se deve aceitar `actor_role` como autorização fornecida
pelo cliente. Os estados retornados são resultados de validação, não prova
de persistência.

As operações persistentes precisam vincular analista, data/hora e observações
à Investigation e conservar evidências. Escalonamento deve criar exatamente
um Incident vinculado e alterar o Alert na mesma transação. A auditoria deve
atender RF15.2 e RN04; os campos de mudança de papel de User não substituem
o registro de mudanças de Status. A abertura de Incident não é responsabilidade
de `validate_escalation_eligibility`.

## Testes

Com dependências instaladas, a partir de `backend/`:

```powershell
python -m pytest tests/test_investigation_rules.py --cov=app.investigations.rules --cov-branch --cov-report=term-missing --cov-fail-under=80 -q
```

Esses testes não precisam de PostgreSQL. Para a suíte completa e metas de
cobertura geral e por módulo, utilize o [README](../README.md#testes-automatizados).
