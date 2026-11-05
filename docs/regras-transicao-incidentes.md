# Regras de transição de Incidents

O módulo valida as transições da seção 9 da [spec](../spec.md), incluindo
RF12, RF13, RF14, RF33 e RN03. É independente de HTTP, persistência e autenticação;
não cria Incidents nem altera entidades.

## Organização e contrato

- [transitions.py](../backend/app/incidents/transitions.py): estados, exceção
  e função de validação.
- [Testes](../backend/tests/test_incident_transitions.py): cenários positivos,
  negativos, limites e ausência de efeitos colaterais, em padrão AAA.

```python
validate_transition(
    current_status: IncidentStatus | str,
    target_status: IncidentStatus | str,
    *,
    containment_description: str | None = None,
    resolution_conclusion: str | None = None,
) -> IncidentStatus
```

`IncidentStatus` é um `StrEnum` com `OPEN`, `UNDER_INVESTIGATION`, `CONTAINED`
e `RESOLVED`. A função recebe estados exatos, como enum ou string, e retorna
o estado de destino validado. Não modifica ou armazena os textos recebidos.

## Transições permitidas

| Origem | Destino | Texto obrigatório |
|---|---|---|
| OPEN | UNDER_INVESTIGATION | Nenhum |
| UNDER_INVESTIGATION | CONTAINED | `containment_description` |
| UNDER_INVESTIGATION | RESOLVED | `resolution_conclusion` |
| CONTAINED | RESOLVED | `resolution_conclusion` |

As demais combinações são recusadas, incluindo permanência no mesmo estado,
transições reversas, OPEN → RESOLVED e saída de RESOLVED.

Qualquer texto fornecido precisa ser string ou `None`, mesmo quando não é
obrigatório para a transição. Um texto obrigatório não pode ser ausente,
vazio ou formado somente por whitespace reconhecido por `str.strip()`.
O teste de preenchimento não normaliza o valor original. Não há tamanho
máximo definido por esse módulo.

## Erros, segurança e integração

Entradas inválidas lançam `IncidentTransitionError`, subclasse de `ValueError`,
com mensagens fixas para estado desconhecido, transição proibida, tipo textual
incorreto ou ausência de texto obrigatório. Valores recebidos não são
incluídos na mensagem. A função não faz I/O, logging ou escrita no banco.

O serviço consumidor deve obter a identidade no servidor, exigir ANALYST ativo,
buscar o estado persistido e controlar concorrência. ADMIN não herda ANALYST.
Validar uma transição não comprova identidade, permissão ou existência da entidade.

Uma alteração persistente deve conservar a descrição ou conclusão, o analista
e a data/hora, além de gravar o Audit Log na mesma transação, conforme RF15.3
e RN04. Campos de mudança de papel de User não representam mudança de Status.
Evidências e associações precisam ser preservadas conforme RN05.

## Testes

Com dependências instaladas, a partir de `backend/`:

```powershell
python -m pytest tests/test_incident_transitions.py --cov=app.incidents.transitions --cov-branch --cov-report=term-missing --cov-fail-under=80 -q
```

Esses testes de domínio não precisam de PostgreSQL. Para executar a suíte
completa e medir as metas geral e por módulo, utilize o [README](../README.md#testes-automatizados).
