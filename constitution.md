# Constituição do Mini SOC

## Arquitetura e simplicidade

- O sistema DEVE preservar o monólito modular, a separação entre API, serviços
  e repositórios e as decisões arquiteturais aprovadas e registradas em ADRs.
- A implementação DEVE analisar e reutilizar modelos, infraestrutura e contratos
  existentes, evitando duplicação, dependências e abstrações desnecessárias.
- Código e nomes DEVEM favorecer legibilidade. Comentários, quando necessários,
  DEVEM ter no máximo três palavras e explicar aspectos relevantes.

## Segurança e integridade

- Autenticação, estado da conta e permissões DEVEM ser verificados no servidor;
  controles visuais NÃO DEVEM substituir autorização ou proteções de sessão.
- Senhas, tokens, cookies, dotenv reais e outros segredos NÃO DEVEM ser publicados
  no Git, em logs ou em artefatos de teste. Dados privados NÃO DEVEM ser
  reproduzidos desnecessariamente em erros ou documentação.
- Persistência DEVE reutilizar a infraestrutura compartilhada, constraints e
  transações para preservar unicidade, referências, auditoria e registros históricos.
- Migrations DEVEM ser revisadas antes da execução. Revisões aplicadas em bancos
  persistentes NÃO DEVEM ser reescritas; evolução DEVE preservar dados e integridade.
  Operações potencialmente destrutivas exigem análise e autorização específica.

## Testes e evidências

- Testes DEVEM seguir AAA (Arrange, Act, Assert), com cenários positivos,
  negativos e de limites, preservando as regressões existentes.
- A cobertura geral DEVE atingir pelo menos 70%; os gates específicos existentes
  de 80% e o CQ01 da especificação DEVEM ser preservados. Testes ou metas NÃO
  DEVEM ser enfraquecidos para obter aprovação.
- Testes PostgreSQL DEVEM usar exclusivamente `mini_soc_test`, com isolamento
  e verificação do nome configurado e do banco real antes de qualquer escrita.
  Dados de desenvolvimento ou produção NÃO DEVEM ser usados.
- Resultados de testes, CI, revisões e aprovações DEVEM ser verificáveis;
  execução local NÃO DEVE ser apresentada como aprovação remota.

## Documentação e rastreabilidade

- Todos os artefatos DEVEM usar linguagem técnica, objetiva, impessoal e
  profissional, incluindo código, comentários, testes, documentação, Issues,
  descrições de PRs e mensagens de commit.
- A documentação versionada DEVE descrever contratos, arquitetura, funcionamento,
  operação e manutenção. Relatórios temporários de execução, estados de branches,
  históricos de integração e narrativas de interação com IA NÃO DEVEM ser
  mantidos como documentos técnicos do projeto.
- Artefatos NÃO DEVEM narrar conversas, prompts, instruções pessoais, confirmações
  informais ou o processo de geração do conteúdo. Contratos e decisões DEVEM
  ser afirmados diretamente; pendências DEVEM ser identificadas tecnicamente.
- Requisitos em [spec.md](spec.md) NÃO DEVEM ser alterados sem revisão. Mudanças
  de comportamento DEVEM manter especificação, código e testes coerentes.
  Decisões arquiteturais relevantes DEVEM ser registradas em ADRs, sem presumir
  aprovação de propostas pendentes.
- Referências RF/RNF/RN, Issues, PRs, commits, ADRs e evidências necessárias à
  auditoria DEVEM ser preservadas nos locais apropriados. Links e arquivos
  modificados DEVEM ser revisados antes de concluir uma alteração.

## Git, colaboração e revisão

- Alterações DEVEM manter escopo definido, branch própria e PR rastreável,
  preservando autoria, histórico e alterações locais. Commits DEVEM seguir
  Conventional Commits, com descrição técnica em português.
- Histórico compartilhado NÃO DEVE ser reescrito. Mudanças NÃO DEVEM ser feitas
  diretamente na main ou em branches de outro responsável sem autorização.
- PRs DEVEM ser revisados pelo outro integrante, com checks aplicáveis à versão
  atual. Merges exigem autorização explícita e NÃO DEVEM contornar proteções.
- Comentários NÃO DEVEM ser publicados em Issues, PRs ou revisões do GitHub.
  Informações necessárias DEVEM usar descrições, documentação permanente ou
  relatórios externos ao repositório, conforme sua finalidade.

## IA, aprendizagem e explicabilidade

- Ferramentas de IA DEVEM operar sob os mesmos contratos, limites de escopo,
  controles de segurança e revisão aplicáveis ao restante do desenvolvimento.
  Suas saídas DEVEM ser verificadas no código e em evidências, sem substituir
  responsabilidade técnica ou aprovação humana.
- Decisões DEVEM ser explicáveis por seu objetivo, alternativas relevantes,
  consequências e validação, com justificativas proporcionais à complexidade.
  A documentação DEVE apoiar compreensão e manutenção, sem narrar sua elaboração.
