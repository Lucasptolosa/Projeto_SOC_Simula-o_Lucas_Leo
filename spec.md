# Mini SOC — Especificação do Sistema

## 1. Visão geral

O **Mini SOC** é um sistema acadêmico de monitoramento e gestão de incidentes de segurança. Ele recebe **Logs simulados**, avalia **Detection Rules**, cria **Alerts** e permite que um **Security Analyst** investigue os alertas, descarte falsos positivos ou abra **Incidents** e acompanhe seu tratamento.

**Fluxo principal:**

```text
Log → Detection Rule → Alert → Investigation
                                  ├─→ False Positive (DISMISSED)
                                  └─→ Incident → Treatment → RESOLVED
```

## 2. Perfis e permissões

| Operação | Security Analyst | Administrator |
|---|:---:|:---:|
| Consultar Logs | Sim | Sim |
| Consultar Alerts e Incidents | Sim | Não |
| Importar lotes de Logs simulados | Não | Sim |
| Investigar e descartar Alerts | Sim | Não |
| Abrir, tratar e resolver Incidents | Sim | Não |
| Consultar Dashboard de segurança | Sim | Não |
| Cadastrar, alterar e desativar Assets | Não | Sim |
| Ativar e desativar Detection Rules predefinidas | Não | Sim |
| Cadastrar, alterar e desativar Users e atribuir papéis | Não | Sim |
| Consultar Audit Logs | Não | Sim |

**Premissa de escopo:** os perfis acima são mutuamente exclusivos no MVP; não há cadastro público de usuários. A criação inicial de uma conta Administrator ocorrerá por procedimento de instalação documentado.

## 3. Entidades e dados mínimos

- **User:** identificador, nome de usuário único, papel (`ANALYST` ou `ADMIN`), estado (`ACTIVE` ou `INACTIVE`) e hash de senha.
- **Asset:** identificador, nome, tipo (`SERVER`, `WORKSTATION` ou `APPLICATION`) e estado (`ACTIVE` ou `INACTIVE`).
- **Log:** `event_id` único, `asset_id`, `occurred_at` com fuso horário, `event_type` e `username`.
- **Detection Rule:** identificador, tipo de regra predefinido (`DR01`, `DR02` ou `DR03`), estado (`ACTIVE` ou `INACTIVE`) e Severity fixa associada ao tipo.- **Alert:** identificador, regra de origem, Log(s) que fundamentam a detecção, Asset, Severity, data/hora e Status.
- **Investigation / Evidence:** Alert associado, analista, observação textual e data/hora do registro.
- **Incident:** identificador, Alert de origem, analista responsável, Status, Severity herdada do Alert, data/hora de abertura e conclusão textual de resolução quando aplicável.
- **Audit Log:** identificador, usuário, ação, entidade afetada e data/hora.

**Nota sobre `username`:** O campo `username` de um Log identifica a conta envolvida no evento monitorado. Essa conta não precisa corresponder a um User cadastrado no Mini SOC, pois os usuários do sistema e as contas dos Assets monitorados pertencem a contextos diferentes.

**Tipos de Log do MVP:** `AUTH_FAILURE`, `AUTH_SUCCESS` e `ADMIN_ACCESS`. Um `Event` é a ocorrência representada por um Log.

**Configuração das Detection Rules:** O MVP possui três Detection Rules predefinidas (`DR01`, `DR02` e `DR03`). Seus parâmetros e sua Severity são fixos conforme a seção 8. O Administrator poderá ativá-las ou desativá-las, mas não cadastrar novos tipos nem alterar seus parâmetros pela aplicação.

### 3.1 Formato proposto de entrada de Logs

Um lote será recebido como um **arquivo JSON com uma lista de 1 a 1.000 objetos**. Cada objeto deverá seguir este exemplo:

```json
{
  "event_id": "evt-001",
  "asset_id": "srv-01",
  "occurred_at": "2026-10-08T14:03:00-03:00",
  "event_type": "AUTH_FAILURE",
  "username": "usuario1"
}
```

Os campos são obrigatórios. `event_id` deve ser único; `asset_id` deve referenciar um Asset existente; `occurred_at` deve conter data/hora e fuso; `event_type` deve pertencer a um dos três tipos de Log citados.

## 4. Requisitos funcionais (RF)

**RF01:** WHEN um User ativo informar nome de usuário e senha correspondentes aos valores cadastrados, THE SYSTEM SHALL autenticá-lo;   

**RF02:** IF as credenciais forem inválidas ou o User estiver inativo, THEN THE SYSTEM SHALL negar o acesso sem informar qual campo estava incorreto.  

**RF03:** WHILE um User estiver autenticado, THE SYSTEM SHALL autorizar somente as operações permitidas ao seu papel conforme a matriz da seção 2.  

**RF04:** WHEN o Administrator informar nome, tipo e estado válidos de um Asset, THE SYSTEM SHALL cadastrá-lo com identificador único;  

**RF05:** WHEN o Administrator solicitar a desativação de um Asset, THE SYSTEM SHALL alterar o estado para `INACTIVE` sem excluir registros históricos.  

**RF06:** WHEN um Administrator enviar um lote JSON de Logs conforme a seção 3.1, THE SYSTEM SHALL validar e persistir cada registro válido com referência ao Asset existente.  

**RF07:** WHEN Logs válidos forem processados, THE SYSTEM SHALL avaliar cada Log, usando seu campo `occurred_at` para as janelas temporais, contra as Detection Rules ativas especificadas na seção 8.  

**RF08:** WHEN uma Detection Rule ativa identificar uma condição definida na seção 8, THE SYSTEM SHALL criar um Alert com identificador, regra aplicada, Logs relacionados, Asset, Severity, data/hora e Status inicial `NEW`.  

**RF09:** WHEN um Alert for criado, THE SYSTEM SHALL atribuir a Severity configurada na Detection Rule que o gerou, limitada a `LOW`, `MEDIUM`, `HIGH` ou `CRITICAL`.  

**RF10:** WHEN um Security Analyst iniciar uma Investigation de um Alert `NEW`, THE SYSTEM SHALL mudar seu Status para `IN_REVIEW` e permitir a inclusão de observações textuais vinculadas ao Alert, ao analista e à data/hora.  

**RF11:** WHEN um Security Analyst solicitar o escalonamento de um Alert `IN_REVIEW` que ainda não possua Incident associado, THE SYSTEM SHALL criar exatamente um Incident com Status inicial `OPEN`, Severity herdada do Alert e responsável inicial igual ao analista solicitante, vinculá-lo ao Alert original e alterar o Status do Alert para `ESCALATED`. A criação do Incident e a alteração do Alert deverão ocorrer de forma atômica, preservando o estado anterior caso a operação falhe.

**RF12:** WHEN um Security Analyst solicitar uma transição de Status de um Incident, THE SYSTEM SHALL executá-la somente se estiver entre as transições autorizadas na seção 9.  

**RF13:** IF uma transição de Incident não estiver autorizada na seção 9, THEN THE SYSTEM SHALL rejeitar a solicitação, retornar uma mensagem de erro e preservar o Status anterior.  

**RF14:** WHEN um Security Analyst solicitar a mudança de Status de um Incident para `RESOLVED`, THE SYSTEM SHALL exigir uma conclusão textual não vazia, armazená-la e registrar quem realizou a resolução e quando.  

**RF15.1:** WHEN um Administrator criar, alterar ou desativar um User ou Asset, ou ativar ou desativar uma Detection Rule predefinida com sucesso, THE SYSTEM SHALL gerar um Audit Log contendo o identificador do usuário responsável, a ação executada, o tipo e identificador da entidade afetada e a data/hora da operação.

**RF15.2:** WHEN um Security Analyst alterar com sucesso o Status de um Alert para `DISMISSED` ou `ESCALATED`, THE SYSTEM SHALL gerar um Audit Log contendo o identificador do usuário responsável, a ação executada, o identificador do Alert, o Status anterior, o novo Status e a data/hora da operação.

**RF15.3:** WHEN um usuário autorizado alterar o Status de um Incident com sucesso, THE SYSTEM SHALL gerar um Audit Log contendo o identificador do usuário responsável, o identificador do Incident, o Status anterior, o novo Status e a data/hora da operação.  

**RF16:** WHEN um Security Analyst consultar a lista de Alerts ou Incidents, com ou sem filtros de Severity, Status, Asset ou intervalo de datas, THE SYSTEM SHALL retornar os registros correspondentes, aplicando conjuntamente todos os filtros informados.

**RF17:** WHEN um Security Analyst abrir o Dashboard, THE SYSTEM SHALL apresentar os totais de Alerts por Severity e Status e os totais de Incidents por Severity e Status, calculados a partir dos registros persistidos.  

**RF18:** WHEN um Administrator solicitar ativação ou desativação de uma Detection Rule existente, THE SYSTEM SHALL atualizar seu estado e usar o novo estado nas avaliações posteriores, preservando os Alerts históricos.  

**RF19.1:** WHEN um Administrator cadastrar um User com nome de usuário único, papel válido (`ADMIN` ou `ANALYST`) e senha, THE SYSTEM SHALL criar a conta com identificador único e estado inicial `ACTIVE`.

**RF19.2:** WHEN um Administrator solicitar a desativação de um User `ACTIVE`, THE SYSTEM SHALL alterar seu estado para `INACTIVE`, impedir novas autenticações e bloquear a utilização de sessões anteriormente autenticadas por esse User, sem excluir seus registros históricos.

**RF20:** WHEN um Security Analyst classificar um Alert `IN_REVIEW` como False Positive e informar uma justificativa não vazia, THE SYSTEM SHALL alterar seu Status para `DISMISSED` e armazenar a justificativa sem criar Incident.  

**RF21:** IF um lote de Logs contiver registros inválidos, THEN THE SYSTEM SHALL rejeitar apenas os registros inválidos, continuar processando os demais e apresentar o número de registros aceitos e rejeitados, com o motivo da rejeição de cada item.  

**RF22:** IF um Log com `event_id` já persistido for enviado novamente, THEN THE SYSTEM SHALL rejeitar sua duplicação e não gerar novos Alerts em decorrência desse reenvio.

**RF23:** WHEN uma Detection Rule estiver com Status `INACTIVE`, THE SYSTEM SHALL ignorá-la durante a avaliação de novos Logs, sem gerar Alerts a partir dessa regra.

**RF24:** WHEN o Status de uma Detection Rule for alterado, THE SYSTEM SHALL preservar o conteúdo e a Severity de todos os Alerts gerados anteriormente à alteração.

**RF25:** IF um Administrator solicitar a alteração do papel associado à sua própria conta, THEN THE SYSTEM SHALL rejeitar a operação e preservar o papel anteriormente atribuído.

**RF26:** WHEN um Administrator alterar com sucesso o papel de outro User, THE SYSTEM SHALL incluir no Audit Log previsto pelo RF15.1 o identificador do User afetado, o papel anterior e o novo papel, sem gerar um segundo registro de auditoria para a mesma operação.

**RF27:** WHEN um User autenticado com papel `ADMIN` ou `ANALYST` consultar Logs, com ou sem filtros de `asset_id`, `event_type`, `username` ou intervalo de `occurred_at`, THE SYSTEM SHALL retornar somente os Logs que atendam conjuntamente aos filtros informados.

**RF28:** WHEN um Administrator consultar Audit Logs, THE SYSTEM SHALL apresentar os registros com identificador do autor, ação executada, entidade afetada e data/hora, ordenados da operação mais recente para a mais antiga.

**RF29:** WHEN um Administrator solicitar a alteração do nome ou tipo de um Asset existente com valores válidos, THE SYSTEM SHALL atualizar os campos informados, preservando o identificador do Asset e suas associações com Logs históricos.

**RF30:** WHEN um Administrator solicitar a alteração do nome de usuário ou papel de outro User, utilizando valores válidos e respeitando a unicidade do nome de usuário, THE SYSTEM SHALL atualizar somente os campos solicitados, preservando o identificador da conta.

**RF31:** IF um Administrator solicitar a desativação ou alteração do papel do último User ativo com papel `ADMIN`, THEN THE SYSTEM SHALL rejeitar a operação e preservar o estado e o papel dessa conta.

**RF32:** IF um Security Analyst solicitar uma transição de Status de Alert não prevista na seção 7, THEN THE SYSTEM SHALL rejeitar a operação, apresentar uma mensagem de erro e preservar o Status anterior.

**RF33:** WHEN um Security Analyst solicitar a transição de um Incident de `UNDER_INVESTIGATION` para `CONTAINED`, THE SYSTEM SHALL exigir e armazenar uma descrição textual não vazia da ação de contenção, vinculada ao Incident, ao analista e à data/hora.

**RF34:** WHEN um Security Analyst consultar a lista de Incidents ordenada por prioridade, THE SYSTEM SHALL apresentá-los na ordem de Severity `CRITICAL`, `HIGH`, `MEDIUM` e `LOW`, com os Incidents mais antigos primeiro em caso de mesma Severity.

## 5. Requisitos não funcionais (RNF)

**RNF01 — Proteção de senhas:** WHEN uma senha for cadastrada, THE SYSTEM SHALL persistir somente um hash produzido pelo algoritmo **Argon2id**, utilizando salt aleatório de pelo menos 16 bytes gerado individualmente para cada hash, sem armazenar a senha original.

**RNF02 — Autorização no servidor:** THE SYSTEM SHALL aplicar a matriz de permissões da seção 2 na camada de servidor, independentemente dos controles visuais da interface.  

**RNF03:** WHEN a aplicação for encerrada normalmente e reiniciada após a confirmação de operações de gravação, THE SYSTEM SHALL permitir recuperar todos os registros previamente confirmados de Users, Assets, Detection Rules, Logs, Alerts, Incidents, observações e Audit Logs, sem perda ou alteração dos dados persistidos.

**RNF04:** WHEN um usuário com perfil `ANALYST` ou `ADMIN` tentar alterar ou excluir um Audit Log por qualquer interface ou API disponibilizada pelo sistema, THE SYSTEM SHALL rejeitar a operação e preservar integralmente o registro original.

**RNF05 — Desempenho de consultas:** WHILE o ambiente de referência possuir 4 núcleos de CPU, 8 GiB de RAM, banco local, 10.000 Logs, 500 Alerts e 100 Incidents, THE SYSTEM SHALL concluir ao menos **90 de 100** consultas à lista de Alerts em **até 2 segundos**, considerando 5 clientes simultâneos.  

**RNF06 — Processamento em lote:** WHILE o ambiente definido no RNF05 estiver em uso, THE SYSTEM SHALL concluir a validação, persistência e avaliação de um lote de 1.000 Logs válidos em **até 15 segundos**.  

**RNF07 — Legibilidade de estados:** THE SYSTEM SHALL exibir o nome textual da Severity e do Status de cada Alert e Incident em suas telas de listagem e detalhe, sem depender exclusivamente de cores.  

**RNF08:** WHEN um desenvolvedor adicionar um novo tipo de Detection Rule utilizando o mecanismo de extensão definido na arquitetura, THE SYSTEM SHALL permitir sua integração sem modificar as implementações das Detection Rules existentes, preservando o resultado dos testes automatizados dessas regras.

**RNF09 — Logs técnicos sem segredos:** WHEN ocorrer erro de importação ou falha não tratada de uma operação no servidor, THE SYSTEM SHALL registrar data/hora, operação e categoria do erro, sem registrar senha, token ou hash de senha.  

**Procedimento de verificação do RNF05:** Preparar o ambiente de referência com 10.000 Logs, 500 Alerts e 100 Incidents. Executar 100 consultas à primeira página de 20 Alerts, distribuídas entre 5 clientes simultâneos. Medir o tempo desde o envio de cada requisição até o recebimento completo da resposta pelo cliente de teste. O requisito será aprovado quando pelo menos 90 consultas forem concluídas em até 2 segundos.

**Procedimento de verificação do RNF06:** Preparar um arquivo contendo 1.000 Logs válidos e ainda não importados. Medir o intervalo entre o início da importação e a conclusão da persistência e da avaliação das Detection Rules, incluindo a geração dos Alerts correspondentes. O requisito será aprovado quando esse processamento for concluído em até 15 segundos no ambiente de referência.

## 6. Regras de negócio (RN)

**RN01:** Todo alerta de segurança deve receber exatamente uma classificação de severidade entre `LOW`, `MEDIUM`, `HIGH` e `CRITICAL`.

**RN02:** A investigação, o descarte como falso positivo e o escalonamento de alertas para incidentes são responsabilidades exclusivas dos profissionais com função de Security Analyst.

**RN03:** Somente profissionais com função de Security Analyst podem autorizar a resolução de um Incident, desde que exista uma conclusão textual não vazia documentando o resultado do tratamento.

**RN04:** Toda investigação, decisão de descarte, escalonamento de alerta ou alteração da etapa de tratamento de um incidente deve possuir registro do profissional responsável e da data/hora da operação.

**RN05:** Logs utilizados como evidências de Alerts ou Incidents devem ser preservados durante toda a operação do ambiente de monitoramento definido para o MVP, inclusive após a conclusão das investigações e a resolução dos incidentes.

**RN06:** Incidentes de segurança devem ser priorizados conforme sua severidade, seguindo a ordem `CRITICAL`, `HIGH`, `MEDIUM` e `LOW`. Em situações de mesma severidade, o incidente com data/hora de abertura mais antiga deve receber prioridade.

## 7. Estados e transições de Alert

| Estado atual | Próximo estado permitido | Ação |
|---|---|---|
| `NEW` | `IN_REVIEW` | Analista inicia investigação |
| `IN_REVIEW` | `DISMISSED` | Analista informa justificativa de falso positivo |
| `IN_REVIEW` | `ESCALATED` | Analista cria Incident vinculado |
| `DISMISSED` | — | Estado terminal no MVP |
| `ESCALATED` | — | Estado terminal no MVP |

Não são permitidas outras transições de Alert no MVP. Os estados `DISMISSED` e `ESCALATED` são terminais e não podem ser alterados por nenhuma operação disponibilizada. Tentativas de transição não autorizadas deverão ser rejeitadas conforme o RF32.

## 8. Detection Rules iniciais

**DR01 — Multiple Failed Logins:** quando forem registrados **5 eventos `AUTH_FAILURE` do mesmo `username` e `asset_id` dentro de 120 segundos**, incluindo os limites da janela de tempo, a regra ativa gera um Alert `HIGH`.  
**Testes mínimos:** 4 falhas não acionam; 5 falhas em até 120 s acionam; 5 falhas distribuídas em mais de 120 s não acionam; regra desativada não aciona.

**DR02 — Successful Login After Multiple Failures:** quando ocorrer um evento `AUTH_SUCCESS` precedido de **3 ou mais `AUTH_FAILURE` do mesmo `username` e `asset_id` no intervalo de 300 segundos anterior ao sucesso, incluindo o limite inferior de 300 segundos e excluindo o instante do próprio sucesso**, a regra ativa gera um Alert `MEDIUM`.  
**Testes mínimos:** 2 falhas seguidas de sucesso não acionam; 3 falhas em 300 s seguidas de sucesso acionam; falhas de outro usuário não contam.

**DR03 — Administrative Access Outside Allowed Hours:** quando ocorrer `ADMIN_ACCESS` **fora de segunda a sexta-feira, das 08h00 (inclusive) às 18h00 (exclusive), no fuso `America/Sao_Paulo`**, a regra ativa gera um Alert `MEDIUM`.  
**Testes mínimos:** acesso na terça às 10h não aciona; terça às 20h aciona; domingo às 10h aciona; terça às 08h não aciona; terça às 18h aciona.

### 8.1 Deduplicação
**Deduplicação da DR01:** Para cada combinação de `username` e `asset_id`, uma sequência de eventos `AUTH_FAILURE` termina quando o intervalo entre duas falhas consecutivas ultrapassar 120 segundos. Cada sequência poderá gerar no máximo um Alert da DR01, desde que contenha pelo menos 5 falhas em uma janela de 120 segundos. Eventos `AUTH_SUCCESS` não encerram automaticamente uma sequência considerada pela DR01. O encerramento dessa sequência depende exclusivamente do intervalo entre eventos `AUTH_FAILURE` consecutivos do mesmo `username` e `asset_id`.

**Deduplicação da DR02:** Para cada combinação de `username` e `asset_id`, cada evento `AUTH_SUCCESS` encerra a sequência de falhas considerada pela DR02. Um Alert somente será gerado se houver pelo menos 3 eventos `AUTH_FAILURE` desde o último `AUTH_SUCCESS`, dentro dos 300 segundos anteriores ao sucesso atual. Falhas anteriores ao último sucesso não poderão ser reutilizadas para gerar outro Alert da DR02.

### 8.2 Ordem de processamento

Os Logs de cada lote deverão ser avaliados em ordem crescente de `occurred_at`. Em caso de empate, será utilizada a ordem crescente de `event_id`.

Para cada combinação de `username` e `asset_id`, um Log recebido em um lote posterior com `occurred_at` menor ou igual ao horário do último Log já processado para essa combinação será rejeitado como evento fora de ordem, sem participar da geração de novos Alerts.

Eventos aceitos de diferentes lotes poderão compor uma mesma sequência de detecção, respeitando as condições temporais e as políticas de deduplicação da DR01 e da DR02.

## 9. Estados e transições de Incident

| Estado atual | Próximo estado permitido | Condição |
|---|---|---|
| `OPEN` | `UNDER_INVESTIGATION` | Analista inicia o tratamento |
| `UNDER_INVESTIGATION` | `CONTAINED` | Analista registra ação de contenção |
| `UNDER_INVESTIGATION` | `RESOLVED` | Analista registra conclusão; caso não exija contenção |
| `CONTAINED` | `RESOLVED` | Analista registra conclusão |
| `RESOLVED` | — | Estado terminal no MVP |

**Proibido:** `OPEN → RESOLVED`, transições reversas e transições não listadas. O papel autorizado é Security Analyst.

A transição para `CONTAINED` deve atender ao RF33. As transições para `RESOLVED` devem atender ao RF14, exigindo conclusão textual não vazia. Todas as transições autorizadas devem ser auditadas conforme o RF15.3.

## 10. Escopo e regras de desenvolvimento

### 10.1 Funcionalidades do MVP

- Login e controle de acesso por dois papéis.
- Cadastro, alteração e desativação de Users e Assets.
- Importação e consulta de Logs simulados em JSON.
- Três Detection Rules predefinidas (`DR01` a `DR03`), com ativação e desativação pelo Administrator.
- Geração, consulta, investigação e descarte/escalonamento de Alerts.
- Abertura e tratamento de Incidents com transições controladas.
- Consulta de Dashboard e Audit Log.
- Persistência e testes automatizados dos fluxos principais.


### 10.2 Regras de engenharia e colaboração

- `spec.md` é a **fonte de verdade**; a Pessoa 1 atua como **Spec Owner**.
- Pessoa 1 lidera Authentication, Authorization, Investigation e Incident Management.
- Pessoa 2 lidera Assets, Logs, Detection Engine, Alerts e Dashboard.
- Toda mudança relevante começa em Issue, segue para branch específica e é entregue por Pull Request revisado pelo outro integrante.
- **Quando uma mudança de código altera comportamento documentado, atualizar `spec.md`, código e testes no mesmo commit lógico.**
- Ambas as pessoas precisam ser autoras de commits reais em suas respectivas funcionalidades.
- Decisões arquiteturais relevantes devem ser documentadas em ADR; `plan.md`, `tasks.md` e `README.md` devem permanecer coerentes com o repositório.
- Não registrar credenciais, tokens nem dados sensíveis no Git ou nos Logs.

## 11. Critérios de qualidade, validação e entrega

**CQ01 — Cobertura automatizada:** Os módulos responsáveis por Detection Rules e transições de Incident deverão apresentar cobertura mínima de 80% das linhas de código, medida por ferramenta de cobertura automatizada definida no planejamento técnico.

**CE01 — Reprodutibilidade do ambiente:** O repositório deverá conter um `README.md` com os pré-requisitos, comandos de instalação, configuração do ambiente, inicialização do banco de dados e execução da aplicação, permitindo iniciar o sistema a partir de um clone novo seguindo as instruções documentadas.

**Critério de aceite do MVP:** O projeto somente será considerado concluído quando os requisitos funcionais implementados tiverem seus critérios de aceite verificados, os requisitos não funcionais forem avaliados conforme seus procedimentos de teste, e os critérios CQ01 e CE01 forem atendidos.

## 12. Glossário

- **SOC (Security Operations Center):** centro de operações de segurança.
- **Security Analyst:** usuário que investiga Alerts e trata Incidents.
- **Administrator:** usuário que administra contas, Assets e Detection Rules.
- **Asset:** recurso monitorado, como servidor, estação ou aplicação.
- **Event:** ocorrência de uma atividade.
- **Log:** registro persistido de um Event.
- **Detection Rule:** regra determinística de detecção aplicada a Logs.
- **Alert:** sinal gerado por uma Detection Rule.
- **Severity:** classificação `LOW`, `MEDIUM`, `HIGH` ou `CRITICAL`.
- **Investigation:** análise de um Alert.
- **Evidence:** observação ou informação associada à Investigation.
- **False Positive:** Alert investigado e descartado por não representar incidente.
- **Incident:** caso escalonado para tratamento.
- **Status:** estado de Alert ou Incident durante o fluxo.
- **Containment:** medida para limitar os efeitos de um Incident.
- **Audit Log:** registro histórico de ações relevantes no sistema.
- **Brute Force:** tentativa repetida de autenticação visando descobrir credenciais.
- **`ACTIVE`:** estado de um User, Asset ou Detection Rule que indica sua condição ativa conforme as operações permitidas pelo sistema.
- **`INACTIVE`:** estado de um User, Asset ou Detection Rule que indica sua condição desativada.
- **`DISMISSED`:** estado terminal de um Alert encerrado como falso positivo após investigação e justificativa.
- **`ESCALATED`:** estado terminal de um Alert que originou um Incident.
- **`UNDER_INVESTIGATION`:** estado de um Incident cujo tratamento foi iniciado pelo Security Analyst.
- **`RESOLVED`:** estado terminal de um Incident cujo tratamento foi concluído e documentado.