# Incidents: persistência, tratamento e consultas

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
de mudanças posteriores no Alert. Não há rotas de exclusão de Incidents.

Identidade inválida/inativa retorna 401; papel ou Origin/CSRF inválidos, 403;
referência inexistente, 404; estado incompatível ou duplicação, 409; entrada
inválida, 422. Respostas protegidas não usam cache e erros não ecoam valores
privados. Escalonamentos concorrentes e disputa com descarte confirmam apenas
uma decisão, sem duplicar Incident ou Audit Log.

## Tratamento persistente

`POST /incidents/{incident_id}/transitions` retorna 200 com PublicIncident.
O corpo é um objeto JSON com `target_status` exato. UNDER_INVESTIGATION não
aceita textos; CONTAINED exige somente `containment_description`; RESOLVED
exige somente `resolution_conclusion`. Campos desconhecidos, textos extras,
nulos, tipos não textuais, vazio/whitespace, NUL e UTF-8 inválido retornam 422.
Textos válidos são preservados sem normalização, truncamento ou novo limite.

O serviço reutiliza `validate_transition()` para decidir os pares autorizados.
Transições repetidas, reversas, não previstas ou após RESOLVED retornam 409.
O estado OPEN não pode passar diretamente para RESOLVED. A resolução a partir
de UNDER_INVESTIGATION não exige contenção prévia.

O Incident conserva `analyst_id` e `opened_at`, relativos à abertura. Contenção
acrescenta `containment_description`, `contained_by` e `contained_at`; resolução
acrescenta `resolution_conclusion`, `resolved_by` e `resolved_at`. Esses campos
também são retornados por `GET /incidents/{incident_id}` e permanecem nulos
antes das operações correspondentes. A resolução preserva a contenção existente.
Um ANALYST ativo distinto do responsável pela abertura pode executar o tratamento.

A API valida a forma da entrada; o repositório recupera o Incident com
`populate_existing` e `SELECT FOR UPDATE`; o serviço coordena as alterações,
sem commit próprio. A identidade é revalidada sob bloqueio antes do Incident.
A ordem User → Incident é comum às transições, sem bloquear ou alterar o Alert.
Após obter o bloqueio, a validação usa o estado atual, inclusive quando a sessão
já carregou a entidade anteriormente. Requisições simultâneas são serializadas;
podem confirmar duas mudanças somente se ambas formarem uma sequência permitida
com base nos estados atualizados, nunca uma sobrescrita a partir de estado antigo.

Cada mudança gera exatamente um Audit Log `INCIDENT_STATUS_CHANGED`, com
`entity_type=INCIDENT`, identificador, autor, old_status/new_status e instante.
O instante é o mesmo dos campos de contenção/resolução. O início do tratamento
usa a auditoria para autoria e instante, sem colunas redundantes. A fronteira
HTTP confirma alteração e auditoria em um único commit; falhas provocam rollback.
Alert ESCALATED, Logs, evidências e observações permanecem preservados.

A [migration 0009](../backend/migrations/versions/0009_incident_treatment.py)
sucede a 0008 e acrescenta seis colunas anuláveis, FKs RESTRICT para Users e
constraints que exigem texto, autor e instante em conjunto. Incidents existentes
mantêm seus campos e recebem valores nulos nos campos novos. Não há backfill,
alteração de migrations anteriores ou downgrade destrutivo.

As operações exigem ANALYST ativo; ADMIN não herda acesso. Escritas preservam
Origin e CSRF. Identidade inválida/inativa retorna 401; acesso negado, 403;
Incident inexistente, 404; conflito de transição, 409; entrada inválida, 422.
Falhas inesperadas retornam erro genérico sem payload ou segredos. A resposta
de sucesso é validada antes do commit e não é devolvida se o commit falhar.

## Consulta paginada e prioridade

`GET /incidents` retorna 200 com `Page[PublicIncident]`: `items`, `total`,
`page` e `page_size`. Reutiliza os mesmos campos públicos do detalhe, incluindo
Status e Severity textuais, abertura e dados de contenção/resolução. Esses dados
apoiam RNF07; a conformidade visual depende das telas, fora deste contrato HTTP.

| Parâmetro | Tipo e contrato |
|---|---|
| `page` | Inteiro de 1 a 10.000; padrão 1. |
| `page_size` | Inteiro de 1 a 100; padrão 20. |
| `status` | OPEN, UNDER_INVESTIGATION, CONTAINED ou RESOLVED; opcional. |
| `severity` | LOW, MEDIUM, HIGH ou CRITICAL; opcional. |
| `asset_id` | UUID do Asset associado ao Alert de origem; opcional. |
| `opened_from` | Data/hora ISO 8601 com fuso explícito; limite inferior inclusivo de opened_at. |
| `opened_to` | Data/hora ISO 8601 com fuso explícito; limite superior inclusivo de opened_at. |

Os limites temporais são opcionais e independentes. `Z` e offsets explícitos
são aceitos; instantes equivalentes em fusos distintos têm a mesma semântica.
Os limites podem ser iguais. Intervalo invertido, data sem fuso, timestamp
numérico, UUID inválido, enum desconhecido, paginação fora dos limites ou
parâmetro desconhecido retornam 422 genérico, sem ecoar entradas.

Filtros presentes são aplicados conjuntamente; os omitidos não restringem.
Asset inexistente retorna lista vazia. Um Asset INACTIVE continua associado
ao histórico e pode ser consultado. Severity filtra o valor persistido no
Incident, sem recalculá-lo pelo Alert ou pela regra. Não há cópia de asset_id
na tabela de Incidents: a consulta utiliza a relação com AlertRecord.

A ordem é fixa, conforme RF34 e RN06: CRITICAL, HIGH, MEDIUM e LOW; na mesma
Severity, opened_at crescente; em empate completo, id crescente. O repositório
aplica CASE, filtros e ORDER BY no PostgreSQL antes de LIMIT/OFFSET. A contagem
usa os mesmos filtros e independe da página. Página além dos resultados retorna
items vazio e mantém total. Em um conjunto estável, páginas não repetem registros;
inclusões ou transições entre requisições podem deslocar resultados em paginação
por offset, sem promessa de snapshot entre chamadas independentes.

O schema estende `PaginationQuery`; o serviço revalida ANALYST ativo e monta
o resultado; o router reutiliza `Page` e as dependências existentes. ADMIN não
herda acesso. Identidade inválida/inativa retorna 401; papel incompatível, 403.
A consulta mantém no-store e não exige Origin/CSRF de escrita. Não faz commit,
altera estados, cria auditoria, executa detecção ou modifica evidências. Nenhuma
migration, tabela ou infraestrutura de paginação adicional é necessária.

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

Os testes de [tratamento](../backend/tests/test_incident_treatment.py) cobrem
transições, terminalidade, textos, identidade, auditoria, rollback e preservação
histórica. Os testes [transacionais](../backend/tests/test_treatment_transactions.py)
verificam concorrência com conexões independentes e evolução de Incidents
persistidos na revisão anterior:

```powershell
python -m pytest tests/test_incident_treatment.py tests/test_treatment_transactions.py -q
```

Os [testes de consulta](../backend/tests/test_incident_queries.py) verificam
filtros, contagem, prioridade antes da paginação, empates, limites temporais,
autorização, ausência de segredos e preservação das tabelas existentes:

```powershell
python -m pytest tests/test_incident_queries.py -q
```
