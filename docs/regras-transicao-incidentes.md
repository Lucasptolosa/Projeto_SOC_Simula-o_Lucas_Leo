# Regras de transição de Incidents

O núcleo de domínio valida as transições da seção 9 da [spec](../spec.md), incluindo
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

## Escalonamento persistente

A camada de aplicação atende RF11 e RF15.2 reutilizando Investigation e
AlertRecord. A validação de elegibilidade exige ANALYST e Alert IN_REVIEW;
a criação inicial usa `IncidentStatus.OPEN`, sem simular uma transição de
tratamento. Não há outra entidade Alert ou Investigation.

- [models.py](../backend/app/incidents/models.py): Incident com UUID, vínculo
  único ao Alert, analista responsável, Severity, Status e opened_at.
- [schemas.py](../backend/app/incidents/schemas.py): corpo vazio de escalonamento
  e resposta pública, sem permitir parâmetros de Severity, papel ou responsável.
- [repository.py](../backend/app/incidents/repository.py): recuperação individual
  e verificação de Incident existente para o Alert.
- [service.py](../backend/app/incidents/service.py): coordenação da criação,
  alteração do Alert e auditoria, sem commit próprio.
- [router.py](../backend/app/incidents/router.py): escalonamento e consulta
  individual com as dependências e fronteira transacional de Investigations.

`POST /investigations/{investigation_id}/escalate` aceita corpo ausente ou JSON
vazio e retorna 201 com id, alert_id, analyst_id, severity, status OPEN e
opened_at. `GET /incidents/{incident_id}` recupera o registro com resposta 200.
Somente ANALYST ativo pode acessar essas operações; ADMIN não herda acesso.
Escrita exige Origin e CSRF, e campos adicionais são rejeitados.

As escritas bloqueiam User e Alert na mesma ordem usada por False Positive.
Após validar a Investigation e o estado, o serviço copia a Severity do Alert,
registra o solicitante e o instante e acrescenta ALERT_ESCALATED com Status
IN_REVIEW/ESCALATED. A auditoria compartilha o instante de abertura. Uma única
transação confirma Incident, Alert e auditoria; falhas revertem o conjunto.

A [migration 0008](../backend/migrations/versions/0008_create_incidents.py)
sucede a 0007, sem modificar revisões existentes. Unicidade de alert_id garante
um Incident por Alert no PostgreSQL; FKs RESTRICT preservam origem e autoria.
O Status reutiliza IncidentStatus e sua Severity é armazenada independentemente
de mudanças posteriores no Alert. Não há rotas de tratamento, resolução,
listagem ou exclusão de Incidents.

Identidade inválida/inativa retorna 401; papel ou Origin/CSRF inválidos, 403;
referência inexistente, 404; estado incompatível ou duplicação, 409; entrada
inválida, 422. Respostas protegidas não usam cache e erros não ecoam valores
privados. Escalonamentos concorrentes e disputa com descarte confirmam apenas
uma decisão, sem duplicar Incident ou Audit Log.

## Testes

Com dependências instaladas, a partir de `backend/`:

```powershell
python -m pytest tests/test_incident_transitions.py --cov=app.incidents.transitions --cov-branch --cov-report=term-missing --cov-fail-under=80 -q
```

Esses testes de domínio não precisam de PostgreSQL. Para executar a suíte
completa e medir as metas geral e por módulo, utilize o [README](../README.md#testes-automatizados).

Os testes de [escalonamento](../backend/tests/test_incident_escalation.py) e
[concorrência](../backend/tests/test_escalation_concurrency.py) usam exclusivamente
mini_soc_test e incluem persistência entre sessões, quatro Severities, estados
inválidos, unicidade real, auditoria, rollback e disputa com False Positive:

```powershell
python -m pytest tests/test_incident_escalation.py tests/test_escalation_concurrency.py -q
```
