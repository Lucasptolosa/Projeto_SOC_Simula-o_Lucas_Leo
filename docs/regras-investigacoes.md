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

