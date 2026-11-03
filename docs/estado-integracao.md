# Estado de integração do Mini SOC — 2026-11-03

## Preparação após o PR #37

A referência atual é `origin/main` em `fc97bb2`, que contém o merge do
PR #37 e o commit `0b4207f` da Pessoa 2. A Issue #35 está encerrada. Foram
integrados testes de limites temporais, isolamento, regras inativas,
desempate, rejeição de datas sem fuso e registro interno de avaliadores.
ADR-002 continua marcado como proposto no arquivo original; não foi alterado.

| PR | Base mantida | Commit adicional | Situação |
|---|---|---|---|
| #30 | main | b36f721 | CI reconciliada com a main atual, sem alteração do workflow. |
| #36 | main | f6450c3 | Administração/web reconciliadas com o PR #37, sem patch de CI duplicado. |
| #32 | ci/testes-automatizados | ebe788d | Base de CI atualizada; núcleo e testes de Incidents preservados. |
| #34 | ci/testes-automatizados | f1c4f7a | Base de CI atualizada; núcleo e testes de Investigations preservados. |

As atualizações usam merges normais para as branches de trabalho, sem
reescrever história. Não houve conflitos textuais. Blobs do motor e dos
dois arquivos de testes de Detection Rules são idênticos aos da main atual.
Os domínios de #32 e #34 também foram comparados aos seus commits anteriores.
A composição dos quatro PRs ficou sem conflitos, sem atualizar referências.

Validação local atual: main com CI, **174 testes/98,29%**; administração/web
com Chromium, **357 testes/98,83%**. Integrações somente em mini_soc_test,
com guardas de nome real, schemas isolados e rollback. Nenhuma migration
foi alterada. actionlint e pip check passaram.

A composição completa após #37 passou em **573 testes/98,90%**, com
Chromium real e cobertura de **100%** nos módulos de Incidents e
Investigations. Os **46 testes** do Detection Engine também passaram
separadamente com cobertura combinada de linhas/ramificações de **97,27%**,
exigindo mínimo de 80%. Alembic confirmou uma única head, 0003 -> 0002 -> 0001.
O snapshot temporário não atualiza branches nem incorpora domínios ao #36.

Execuções reais após a atualização:

- [#30: 174 testes/98,29%](https://github.com/Lucasptolosa/Projeto_SOC_Simula-o_Lucas_Leo/actions/runs/41733219439).
- [#32: 278 testes/98,37%, domínio 100%](https://github.com/Lucasptolosa/Projeto_SOC_Simula-o_Lucas_Leo/actions/runs/41733225364).
- [#34: 286 testes/98,37%, domínio 100%](https://github.com/Lucasptolosa/Projeto_SOC_Simula-o_Lucas_Leo/actions/runs/41733234059).

O resultado atual da composição completa e a execução Linux/Chromium do
#36 são registrados na descrição desse PR. A validação do #36 pode usar
temporariamente a base de CI em draft, sem copiar o workflow para sua branch;
seu destino final continua sendo main. Reconfirmar os checks após integrar #30.

Ordem operacional: **#30 -> #36 -> #32 -> #34**. Depois do merge autorizado
de #30, retargetar #32 e #34 para main e validar novamente. Eles dependem
somente de #30 e são independentes entre si. Encerrar #29 após #30;
#21/#23/#25/#27 após #36; #31 após #32; #33 após #34. A #12 continua com a
Pessoa 2. Nenhum merge na main, force push, exclusão de branch ou comentário
no GitHub foi realizado nesta preparação.

## Diagnóstico histórico anterior ao PR #37

O restante deste documento preserva o levantamento anterior. As referências
a main 4a956bc, Issue #35 aberta, 137/320/536 testes e execuções antigas são
históricas; o estado atual é o da seção acima e das descrições dos PRs.

Diagnóstico por arquivos, blobs e ancestralidade, além do estado dos PRs.
Referência da main: `4a956bc`. Não foi realizado merge na main, force push,
exclusão de branches ou reescrita de histórico durante esta organização.

## Issues abertas no início

| Issue | PR associado | Situação comprovada e encaminhamento |
|---|---|---|
| #12 — Alerts | Sem PR de persistência/consultas encontrado | Aberta, Pessoa 2; Alert do Detection Engine ainda é dataclass sem persistência/API. |
| #18 — RBAC | #19, promovido por #20 | Código/commit/testes na main; encerrada após validação independente do escopo de infraestrutura. |
| #21 — Gestão de Users | #22 | Implementada em branch intermediária; manter aberta até o PR desta integração chegar à main. |
| #23 — Consultas administrativas | #24 | Implementada em branch intermediária; manter aberta até a promoção à main. |
| #25 — Interface web | #26 | Implementada em branch intermediária; manter aberta até a promoção à main. |
| #27 — Gestão visual de Users | #28 | Implementada em branch intermediária; manter aberta até a promoção à main. |
| #29 — CI | #30 | PR aberto para main, mergeável e CI aprovada; manter aberta até integração. |
| #31 — Domínio Incidents | #32 | PR aberto sobre CI, domínio implementado, persistência/auditoria fora do escopo; manter aberta até integração. |
| #33 — Domínio Investigations | #34 | PR aberto sobre CI, independente de Incidents; manter aberta até integração. |
| #35 — Adequação das Detection Rules | Sem PR de adequação encontrado; #11 é histórico | Aberta, Pessoa 2; limites, isolamento, ordenação, fuso, extensão e AAA continuam pendentes. |

A #18 foi encerrada porque seu escopo é a infraestrutura require_roles,
com critérios atendidos e testes na main. Isso não encerra RF03/RNF02 para
todo o MVP. As demais Issues permanecem abertas por ausência de integração
ou de implementação dentro de seu escopo; nenhuma foi fechada por quantidade.

## Todos os PRs encontrados no diagnóstico

| PR | Destino real | Estado | Conteúdo na main? |
|---|---|---|---|
| #2 — Spec | main | Merged | Sim. |
| #4 — ADR | main | Merged | Sim. |
| #6 — Backend inicial | main | Merged | Sim. |
| #11 — Detection Rules | main | Merged | Sim, dentro do escopo original; não conclui a nova #35. |
| #13 — Persistência | main | Merged | Sim. |
| #15 — Users/bootstrap | main | Merged | Sim. |
| #17 — Autenticação | codex/persistencia-users | Merged | Código chegou depois pelo #20; o merge específico do #17 não é ancestral da main. |
| #19 — RBAC | codex/autenticacao | Merged | Sim, promovido pelo #20. |
| #20 — Promoção de autenticação | main | Merged | Sim, inclui autenticação e RBAC. |
| #22 — Gestão de Users/auditoria | feat/autorizacao-papeis | Merged | Não. |
| #24 — Consultas | feat/gerenciamento-usuarios | Merged | Não. |
| #26 — Interface web | feat/consultas-administrativas | Merged | Não. |
| #28 — Gestão visual | feat/interface-web-admin | Merged | Não. |
| #30 — CI | main | Aberto, mergeável | Não. |
| #32 — Incidents | ci/testes-automatizados | Aberto, mergeável | Não. |
| #34 — Investigations | ci/testes-automatizados | Aberto, mergeável | Não. |

Os PRs antigos foram preservados. O estado merged de #22/#24/#26/#28 não
significa integração na main. A branch feat/interface-web-admin contém um
merge posterior de #28; sua árvore é equivalente à branch final
feat/interface-gestao-usuarios. Não existe PR aberto duplicando a promoção
administrativa para main.

## Promoção administrativa e web

Branch preparada: `integracao/administracao-web`, criada de `origin/main`
atualizada por fast-forward. Foram selecionados somente os quatro commits
exclusivos, na ordem de dependência. Autenticação e RBAC já presentes na
main não foram reaplicados.

| Origem | Novo commit | Conteúdo |
|---|---|---|
| 44a4193 | ecacfd9 | Gestão de Users, auditoria, revogação e consistência transacional. |
| 51bd8b8 | 2923ec8 | Consultas paginadas, filtros, projeções públicas e auditoria somente leitura. |
| 71a360b | dc6414e | Login/logout, área autenticada e consultas web. |
| c489160 | 48f9569 | Cadastro/edição/desativação pela interface. |

Foi usado cherry-pick -x: preserva autoria e registra o SHA original sem
trazer os merges intermediários confusos. Os quatro patches eram exclusivos
segundo git cherry; não havia equivalentes na main. Os novos SHAs são a
reaplicação rastreável desses patches, não funcionalidades duplicadas na main.
Nenhuma branch de origem foi reescrita. Não houve conflito nessa aplicação.

Antes da documentação de organização, a árvore completa era idêntica a
c489160. O código de produção/testes continua idêntico depois das mudanças
documentais. A comparação do novo PR deve ser feita contra main; ela mostra
somente administração/web ainda ausentes, além deste diagnóstico.

O PR desta branch tem main como destino final e vincula #21/#23/#25/#27.
Enquanto #30 estiver pendente, uma base temporária de CI pode ser usada no
mesmo PR em draft para validar Chromium/Linux; após a validação, a base é
ajustada para main. Isso não importa a CI como patch duplicado nem cria outro
PR. O contexto, merge virtual testado e execução real são registrados na
descrição do PR. Após #30 chegar à main, confirmar novamente os checks da
integração proposta antes de aprovar seu merge.

## Reconciliação de Incidents e Investigations

git merge-tree comprovou conflitos reais em README.md e
.github/workflows/testes.yml entre as heads originais #32 e #34. Nenhum
conflito existia nas regras ou nos testes de domínio.

- #32 recebeu `46ebdd9`: sua documentação foi movida integralmente para
  docs/regras-transicao-incidentes.md, com link no trecho de cobertura.
- #34 recebeu `56453bb`: documentação movida integralmente para
  docs/regras-investigacoes.md, com link no trecho de testes. Seu gate de
  80% ficou após a limpeza do dotenv; o de Incidents fica antes dela.
- Os gates continuam usando os dados de cobertura da suíte completa. A
  limpeza não remove .coverage; nenhum limite/asserção foi reduzido.
- Arquivos backend das duas branches são idênticos aos commits anteriores.
  Os novos commits são aditivos, sem rebase/force push e sem merge de um
  domínio no outro. Ambos continuam dependendo somente de #30.

A composição administrativa + CI + #32 + #34 foi simulada com objetos Git
sem atualizar refs e exportada para cache ignorado. Ela ficou sem conflitos.
Os blobs de Detection Engine e seus testes são idênticos aos da main;
normalizações LF/CRLF de exportação não foram tratadas como mudanças de código.

## Validações realizadas

| Versão testada localmente | Testes | Cobertura geral | Cobertura específica |
|---|---:|---:|---|
| Main 4a956bc | 137 aprovados | 97,82% | RBAC 100%. |
| Administração/web reconciliadas | 320 aprovados | 98,56% | Componentes novos preservados. |
| Composição administrativa + CI + Incidents + Investigations | 536 aprovados | 98,64% | Incidents 100%, Investigations 100%. |

Python local 3.14.8/Windows, pytest e Chromium real. As integrações usam
somente mini_soc_test, schemas aleatórios, savepoints e rollback. Os dotenv
locais foram preservados; nada foi aplicado em mini_soc_dev. Não houve
criação de credenciais reais, upload de traces/cookies ou alterações de dados
permanentes. A composição é validação local, não uma alegação de merge ou
de execução remota com 536 testes.

Alembic apresenta uma única head, 0003_create_audit_logs, encadeada a
0002_create_auth_sessions e 0001_create_users. Comparação de metadata,
constraints, rollback e proteção contra duplicação continuam nos testes.
Nenhuma migration foi criada ou duplicada por esta organização. A tabela
de auditoria é a mesma da entrega original #22.

CI real conferida:

- [#30 — 137 testes/97,82%](https://github.com/Lucasptolosa/Projeto_SOC_Simula-o_Lucas_Leo/actions/runs/41716582292), sem conflitos com a main atual.
- [#32 após reconciliação](https://github.com/Lucasptolosa/Projeto_SOC_Simula-o_Lucas_Leo/actions/runs/41728459834), aprovada, mantendo o gate de 80%.
- [#34 após reconciliação](https://github.com/Lucasptolosa/Projeto_SOC_Simula-o_Lucas_Leo/actions/runs/41728499718), aprovada, mantendo o gate de 80%.
- A execução Linux/Chromium administrativa é registrada no novo PR desta
  branch. Resultado local não é apresentado como resultado de GitHub Actions.

O workflow #30 permanece sem alteração: Python 3.14, permissões contents:
read, Actions oficiais fixadas por SHA, PostgreSQL efêmero/role restrita,
70% geral, Chromium condicional e ausência de artefatos sensíveis. Não havia
aprovação de revisão registrada nos PRs abertos no diagnóstico; CI verde
não substitui a revisão da outra pessoa ou proteção obrigatória de branch.

## Ordem de revisão e integração

1. Revisar e autorizar #30 -> main. Isso disponibiliza a CI na main e permite
   encerrar #29 após integração comprovada.
2. Revisar o PR de integracao/administracao-web -> main, confirmar seus checks
   com a CI integrada e autorizar o merge. Só então encerrar #21/#23/#25/#27.
3. Ajustar a base de #32 para main após #30, sem duplicar CI ou administração;
   validar a proposta atual e revisar/integrar Incidents. Encerrar #31 dentro
   do seu escopo de domínio, sem declarar persistência/auditoria concluídas.
4. Ajustar a base de #34 para main após #30, validar e revisar/integrar
   Investigations. Encerrar #33 dentro de seu escopo. Essa posição é uma
   ordem operacional sugerida; #34 não depende de #32.
5. Continuar #12 e #35 com a Pessoa 2. Não misturar persistência de Alerts ou
   correções de Detection Rules nesta organização.

Nenhum desses merges está autorizado nesta tarefa. Main continua com
spec/ADR, Detection Engine, persistência de Users/bootstrap, autenticação e
RBAC; administração/web, CI e os dois núcleos de domínio aguardam promoção.
Assets/Logs persistidos, Alerts/Investigation/Incident transacionais,
auditoria desses fluxos e Dashboard continuam para suas próprias entregas.
