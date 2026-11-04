# Correção da importação de Logs

Branch própria `fix/validacao-importacao-logs`, baseada na head do PR #41.
Nenhuma alteração direta na branch da Pessoa 2. Esta entrega não gera Alerts,
não acrescenta funcionalidades e não encerra #40 ou #12.

## Contratos aprovados

Aceite confirmado explicitamente pelo usuário no chat do Codex em 2026-11-04:
os dois integrantes do projeto aprovaram as quatro decisões abaixo. Esse
registro não é uma revisão APPROVED do GitHub nem uma autorização de merge.

| Decisão | Estado |
|---|---|
| Limitar event_id a 1.024 bytes UTF-8 | Aprovado; validação e constraint implementadas no #44. |
| Aceitar eventos de Asset INACTIVE | Aprovado; implementado no #41. |
| Preservar textos sem normalização e sem truncamento | Aprovado; nenhum valor válido é modificado. |
| Rejeitar campos desconhecidos por registro | Aprovado; implementado no #41. |

O aceite decorre da confirmação acima, não da mera existência do código.
O limite de username não foi alterado. O formato principal de Logs e os RF
existentes são preservados. A incorporação do #44 ainda depende da revisão da
Pessoa 2 e de autorização específica para alterar a branch compartilhada;
o merge do #41 à main exige autorização própria.

## Validação e persistência

A chave primária textual usa índice B-tree, cuja capacidade por entrada é
limitada. Texto sem limite na API não garante que todo identificador caiba no
índice. O limite aprovado de 1.024 bytes é medido com encode UTF-8 no Pydantic e
octet_length(convert_to(event_id, 'UTF8')) no PostgreSQL; não é contagem de caracteres. Assim, 512 caracteres
de dois bytes ou 256 de quatro bytes podem atingir exatamente o limite.

EVENT_ID_MAX_BYTES e ck_logs_event_id_bytes refletem o mesmo contrato. A
migration 0005 ainda não integrada foi ajustada com a constraint equivalente;
ela permanece após 0004, sem nova head ou tabela duplicada. Metadata e schema
são comparados pelos testes. PostgreSQL não armazena NUL em text; a validação
agora o recusa antes do SQL em ambos os campos, com razões fixas existentes.

Registros inválidos retornam invalid_event_id ou invalid_username e não
interrompem os válidos anteriores/posteriores. A resposta só ocorre após
commit. Falhas operacionais inesperadas continuam revertendo o lote inteiro.

Se uma versão anterior da 0005 já tiver sido aplicada em banco persistente,
editar seu arquivo não atualiza esse banco. Não executar downgrade nem apagar
dados: avaliar uma migration aditiva antes de instalar em tal ambiente. Nesta
entrega, migrations são executadas somente em schemas isolados de mini_soc_test.

## Três destinos de dados

Respostas HTTP e logger da aplicação usam razões/mensagens fixas. O mecanismo
hide_parameters do SQLAlchemy não controla o log do processo PostgreSQL.
Uma violação CHECK pode incluir a linha rejeitada em DETAIL, mesmo com os
parâmetros de bind omitidos. A reprodução utiliza apenas marcadores sintéticos.

Na CI, o bootstrap configura somente mini_soc_test no container descartável:

| Parâmetro | Valor | Efeito |
|---|---|---|
| log_error_verbosity | terse | Omite DETAIL, HINT, QUERY e CONTEXT. |
| log_min_error_statement | panic | Evita anexar SQL aos erros comuns; não desabilita o registro do erro primário. |
| log_statement | none | Desabilita logging geral de statements. |
| log_parameter_max_length / log_parameter_max_length_on_error | 0 / 0 | Omite os valores de parâmetros. |
| log_min_duration_statement / log_min_duration_sample | -1 / -1 | Desabilita logging de SQL por duração/amostragem. |
| log_transaction_sample_rate | 0 | Desabilita amostragem de transações. |

A verificação real roda depois de instalar dependências. Primeiro uma sessão
administrativa isolada usa log_error_verbosity=DEFAULT por SET LOCAL, provoca CHECK e confirma um
marcador nos logs reais do container. A conexão termina e reverte seu estado.
Depois a role de aplicação conecta exclusivamente a mini_soc_test, confere o
perfil efetivo, provoca outra CHECK em tabela temporária e verifica a ausência
do segundo marcador. Se o log não estiver acessível, o controle positivo falha;
ausência de saída não é tratada como prova de proteção. O script publica somente
o resultado dos controles e mascara os marcadores antes de usá-los, inclusive
para a eventual impressão automática dos logs do container pelo Actions na
limpeza. Não faz upload de logs brutos, senhas ou dados como artefatos.

O perfil conserva horário, severidade e mensagem primária, mas perde SQL,
parâmetros e detalhes úteis à investigação. Mensagens primárias de outros
erros, extensões, logs externos e configurações diferentes ainda podem expor
dados. O teste não prova proteção total para todo erro ou ambiente.

Nenhuma configuração permanente do PostgreSQL compartilhado/local é alterada.
O mantenedor deve avaliar a política de banco/role, permissões e diagnóstico
antes de qualquer adoção fora do runner; o perfil da CI não é aplicado pela
aplicação nem pela migration 0005.

## Regressões

Em backend, usando exclusivamente mini_soc_test:

```powershell
python -m pytest tests/test_log_validation.py tests/test_logs.py tests/test_users.py -q
python -m pytest --cov=app --cov-report=term-missing --cov-fail-under=70 -q
```

Os testes novos seguem AAA e incluem 1.024/1.025 bytes, multibyte, milhares de
caracteres, NUL e UTF-8 inválido, persistência após commit, rejeições por posição,
ausência de INSERT para inválidos e constraint real. Os testes anteriores de
unicidade, duas conexões concorrentes, autorização e rollback são preservados.
A composição temporária com a main atual mantém Chromium e os gates específicos
de Incidents/Investigations em 80%, além dos 70% gerais. O PR de correção é
direcionado à branch do #41 e aguarda revisão/autorização de incorporação;
a execução dessa base não inclui os dois domínios que já estão na main, por
isso a composição também é testada à parte.

Referências: [B-tree PostgreSQL 17](https://www.postgresql.org/docs/17/btree.html)
e [logging PostgreSQL 17](https://www.postgresql.org/docs/17/runtime-config-logging.html).
