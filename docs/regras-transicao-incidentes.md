## Regras de transição de Incidents — Issue #31

`backend/app/incidents/transitions.py` implementa somente o núcleo de domínio
da seção 9 da spec. IncidentStatus é um StrEnum com OPEN, UNDER_INVESTIGATION,
CONTAINED e RESOLVED. Não há modelo ORM, migration, API, serviço de banco ou
dependência de Alerts nesta entrega.

| Origem | Destino permitido | Texto obrigatório |
|---|---|---|
| OPEN | UNDER_INVESTIGATION | Nenhum. |
| UNDER_INVESTIGATION | CONTAINED | containment_description. |
| UNDER_INVESTIGATION | RESOLVED | resolution_conclusion. |
| CONTAINED | RESOLVED | resolution_conclusion. |
| RESOLVED | Nenhum | Estado terminal. |

`validate_transition(current_status, target_status, *, containment_description=None,
resolution_conclusion=None)` aceita IncidentStatus ou strings exatamente iguais
aos seus valores, sem conversão de caixa ou remoção de espaços dos estados.
Retorna o destino como IncidentStatus apenas após todas as validações. Em
caso de erro, lança IncidentTransitionError, derivado de ValueError, com
mensagem fixa, sem incluir os valores recebidos.

Exemplo de validação pura, executado a partir da pasta backend:

```python
from app.incidents.transitions import IncidentStatus, validate_transition

destination = validate_transition(
    IncidentStatus.UNDER_INVESTIGATION,
    IncidentStatus.CONTAINED,
    containment_description="Servidor isolado da rede.",
)
assert destination is IncidentStatus.CONTAINED
```

OPEN -> RESOLVED, reversões, repetição do estado e qualquer par não listado
são rejeitados, mesmo quando há textos válidos. Status desconhecidos ou
tipos inválidos não são aceitos. Os textos fornecidos devem ser str ou None;
nas transições em que são obrigatórios, None, vazio e somente whitespace
(inclusive tabulações/quebras e espaços Unicode) são recusados por strip().
O conteúdo original não é normalizado nem truncado. Um caractere textual é
válido; não foi inventado limite máximo ausente da spec. Os textos opcionais
de outras transições não se tornam obrigatórios nem são persistidos pelo
validador. Caracteres de formatação que Python não considera whitespace não
recebem uma política adicional nesta entrega.

A função não recebe uma entidade mutável, não escreve no banco, não gera
auditoria, não faz logging e não muda o estado por conta própria. Ela devolve
somente um destino válido; autenticação e permissões devem ser verificadas
pelo futuro chamador, que só deve atribuir o destino após sucesso.

### Integração futura

O fluxo persistido continuará dependente de Alerts e de um modelo completo
de Incident a ser tratado em outra Issue. O serviço futuro deverá:

1. Recuperar o Incident no PostgreSQL dentro da Session/transação apropriada,
   definindo o controle de concorrência antes de permitir gravações.
2. Verificar autenticação, User ACTIVE e papel ANALYST. As dependências da
   futura API também devem negar acesso antes de expor dados.
3. Chamar validate_transition com o estado atual e os textos recebidos.
4. Persistir o destino retornado somente se a validação tiver sucesso.
5. Registrar responsável, data/hora e descrição/conclusão exigida, mantendo
   os valores originais validados.
6. Acrescentar o Audit Log correspondente com estados anterior/novo.
7. Confirmar todas as gravações na mesma transação; qualquer falha deve
   reverter estado, textos, autoria e auditoria.

Interfaces já identificadas para reutilização: get_current_user em
app/auth/dependencies.py e require_roles(UserRole.ANALYST) em
app/auth/authorization.py, presentes na main remota. ADMIN não herda
permissões de ANALYST. get_session/fábrica de Session continuam sendo a
fronteira de persistência compartilhada. O módulo de domínio não importa
essas interfaces e pode ser usado antes da integração dessas funcionalidades
na base empilhada atual.

O módulo administrativo de auditoria, disponível nas branches anteriores,
oferece AuditLog e append_audit(db, ...), que adiciona eventos à Session sem
commit próprio. Seu contrato atual contém autor, ação, entidade e horário,
mas os campos adicionais old_role/new_role são exclusivos de papéis. Eles
não devem armazenar estados de Incident. A representação de estado anterior/
novo e os textos/autoria persistidos precisam de uma integração futura
específica; esta entrega não altera tabelas ou contratos de auditoria.

| Referência | Entrega e limite |
|---|---|
| RF12 / seção 9 | Matriz validada no domínio; execução autenticada/persistida ainda pendente. |
| RF13 | Rejeição com erro e entradas preservadas; resposta HTTP e rollback do fluxo persistido pendentes. |
| RF14 | Conclusão textual obrigatória validada; armazenamento, responsável e horário pendentes. |
| RF33 | Descrição de contenção obrigatória validada; armazenamento, responsável e horário pendentes. |
| RF15.3 / RN04 | Não implementados; auditoria e registros persistidos dependem da integração futura. |
| CQ01 | Meta de 80% do novo módulo exigida separadamente, mantendo 70% geral. |

### Testes e cobertura

Os testes novos em tests/test_incident_transitions.py seguem AAA e são
puramente unitários: não solicitam fixtures de banco. Cobrem os 16 pares de
estados, enum/strings válidas, tipos/status inválidos, textos obrigatórios,
whitespace, acentos/multilinhas, mínimo de um caractere, ausência de limite
inventado e preservação das entradas em sucesso/falha. Os testes anteriores
continuam sem alterações; suas integrações usam somente mini_soc_test.

Validação local desta base empilhada: **170 testes aprovados** (104 novos e
66 anteriores), com **97,64% de cobertura geral** e **100% no módulo de
transições**. A execução isolada dos 104 testes também atingiu 100% de
linhas e ramificações. O resultado real da CI será registrado no PR.

Na pasta backend:

```powershell
python -m pytest tests/test_incident_transitions.py --cov=app.incidents.transitions --cov-branch --cov-report=term-missing --cov-fail-under=80 -q
python -m pytest --cov=app --cov-report=term-missing --cov-fail-under=70 -q
python -m coverage report --include=app/incidents/transitions.py --fail-under=80
```

O último comando avalia a cobertura do módulo com os dados da suíte completa.
A CI adiciona a mesma verificação específica após a aprovação geral, sem
reduzir metas, filtrar testes ou mudar o workflow do PR #30 na sua branch.
Esta entrega usa feat/regras-transicao-incidentes sobre ci/testes-automatizados
enquanto #30 estiver aberto; a integração deve preservar essa dependência.
Não há dependência de pacote novo nem alteração em código da Pessoa 2,
spec.md ou ADR-001. Não foram criados plan.md/tasks.md ausentes apenas para
esta entrega.

