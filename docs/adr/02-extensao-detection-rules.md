# ADR-002 - Extensão do Detection Engine

Status: proposto para revisão da dupla; não aprovado.
Issue: #35 - Validação e adequação das Detection Rules.
Referências: ADR-001, RNF08, RF07, RF23 e seções 8 a 8.2 de spec.md.

## Contexto

O motor chamava diretamente três métodos. RNF08 exige incorporar uma regra
por mecanismo de extensão sem modificar as implementações existentes.
O MVP continua limitado a DR01, DR02 e DR03 pela interface da aplicação.

## Proposta implementada para revisão

Manter o motor e suas dataclasses e registrar avaliadores em um dicionário
ordenado, indexado pelo identificador da regra. `register_rule(rule, evaluator)`
recebe uma DetectionRule e uma função que recebe Log e retorna Alert ou None.
Identificador duplicado e avaliador não chamável são recusados antes de mutação.
O desenvolvedor fornece metadados válidos e o Alert correspondente à regra;
este é um contrato Python interno, não uma API para entradas de usuários.

As regras iniciais são registradas na mesma coleção. `process_batch` ordena
os eventos, atualiza o histórico e chama apenas avaliadores de regras ativas.
Uma extensão requer somente registro e testes, sem modificar DR01-DR03.

O acompanhamento de falhas permanece separado da emissão de Alerts.
Preserva-se o comportamento já existente: o histórico acompanha falhas mesmo
com a regra inativa, sem gerar Alert; um AUTH_SUCCESS consome o histórico da
DR02 mesmo inativa. A reativação afeta somente avaliações posteriores.
Não há reprocessamento automático dos eventos anteriores.

## Consequências e limites

- Biblioteca padrão apenas; sem dependência, serviço ou framework novo.
- Mantém imports públicos e parâmetros temporais/severidades das três regras.
- O registro é feito na inicialização, antes de processar lotes; não oferece
  atualização concorrente de avaliadores nem cadastro de regras pelo usuário.
- O motor permanece em memória e exige instância/estado controlados pelo serviço;
  persistência, concorrência, idempotência global e histórico durável são futuros.
- O contrato interno de extensões é verificado por testes, não é uma sandbox
  para código externo nem uma validação de contrato completa em runtime.
- A dupla deve revisar esta decisão antes da integração. ADR-001 permanece válido.
