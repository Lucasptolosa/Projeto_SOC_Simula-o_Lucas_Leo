# ADR-003 — Estado transacional do Detection Engine

Status: proposto para revisão da dupla.
Issue: #47. Referências: ADR-001, ADR-002, spec 3.1.2, 8 a 8.2, RF07/RF08/RF22 e RNF03.

## Contexto

O motor existente implementa DR01-DR03 e o registro de avaliadores, mas guarda
histórico e contador em memória. Recriar uma instância sem restaurar estado perde
sequências e deduplicação. Compartilhar uma instância global deixa mutações de
memória sobreviverem a rollback e não coordena processos concorrentes.

## Proposta implementada

Manter o motor e seus avaliadores. O adaptador interno `app.detection.state`
serializa o estado em JSONB versionado e restaura uma instância por transação.
Somente esse adaptador acessa os campos privados de estado; alterações desses
campos exigem revisão do formato e dos testes de ida/volta e continuidade.
Não se serializam código executável, callbacks nem objetos pickle.

Uma linha singleton de `detection_state`, criada por migration, é bloqueada
com SELECT FOR UPDATE antes da inserção de Logs. Sob READ COMMITTED, cada lote
carrega o último estado confirmado. O mesmo bloqueio coordena instâncias da API
e é liberado pelo commit/rollback, sem infraestrutura de banco adicional.

Ordem de bloqueios: autor atual, estado singleton, Assets consultados durante
ingestão, catálogo ordenado por identificador durante avaliação. Uma futura
operação de alteração de regras deve respeitar a coordenação pelo estado antes
de bloquear regras, e registrar auditoria na mesma transação. Não é criada
nesta issue uma API de administração de regras.

As três regras predefinidas são semeadas uma única vez pela migration, ativas
e com Severity fixa. A API não recria catálogo/estado ausente: falha e reverte.
Alerts usam UUID, snapshot de Severity/Status/instante e FK para regra, Asset e
evento acionador. A tabela de evidências preserva a ordem dos Logs. Unicidade
regra/evento acionador é proteção adicional, não substitui deduplicação temporal.

O router conserva a responsabilidade pelo único commit. Serviço e adaptador
não confirmam transações. Uma falha após geração de Alerts reverte também Logs,
evidências e novo snapshot. Nenhum estado mutável global é reutilizado.

## Consequências

- Reutiliza Settings, Engine, Session Factory, Base e cadeia Alembic existentes.
- Não altera os algoritmos, janelas nem mecanismo de extensão DR01-DR03.
- Coordenação global reduz paralelismo: adequada à simplicidade do MVP, mas
  desempenho RNF06 precisa de medição no ambiente especificado.
- Snapshot contém históricos e cresce com a atividade; não são introduzidas
  retenção ou compactação que possam alterar evidências ou sequências.
- A migration é aditiva e não processa Logs anteriores. O ponto de início
  funcional foi alinhado na spec; reprocessamento exige decisão separada.
- Registro interno de extensões continua disponível no motor. O catálogo
  persistente/API do MVP permanece limitado às três regras predefinidas.
- Falhas de versão/estrutura do snapshot abortam a operação; não há reset
  silencioso, downgrade destrutivo nem descarte de histórico.

Esta decisão aguarda revisão arquitetural. Não declara aprovação do ADR-002,
conclusão da gestão de Alerts ou de todos os requisitos de recuperação do MVP.
