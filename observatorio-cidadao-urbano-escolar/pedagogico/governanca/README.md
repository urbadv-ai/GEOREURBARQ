# Governança, Roadmap e Rastreabilidade — OCUE

Esta pasta concentra as fontes de controle do desenvolvimento do **Programa Educacional para Cidades e Cidadania / Observatório Cidadão Urbano Escolar (OCUE)**.

## Fonte de verdade por função

| Função | Arquivo vigente | Regra |
|---|---|---|
| Ponto final e ordem das fases | `ROADMAP_PONTO_FINAL_v1_0.md` | Define P1–P7, metas 55/68/75/85/90/95/100 e gates. |
| Registro operacional de todos os entregáveis | `REGISTRO_MESTRE_EXECUCAO_v1_1.json` | Fonte operacional de verdade. Contém 64 IDs de entregáveis com status, fração, evidência, gate e pendência. |
| Leitura executiva do registro | `REGISTRO_MESTRE_EXECUCAO_v1_1.md` | Resumo humano; não substitui o JSON. |
| Snapshot histórico inicial | `maturidade_projeto_v1_0.json` | Preserva 41,45% em 2026-08-26. Não sobrescrever. |
| Snapshot auditado da branch | `maturidade_projeto_v1_1.json` | 52,953125% preciso / 52,95% de comunicação. Ainda não homologado em `main`. |
| Validação do Registro Mestre | `validate_registro_mestre_execucao.py` | Verifica 7 fases, 64 entregáveis, IDs, frações e existência das evidências creditadas. |
| Validação da maturidade | `validate_maturidade_projeto.py` | Recalcula score, pesos, contribuição das dimensões e vínculo com o Registro Mestre. |

## Workflows de governança

- `.github/workflows/ocue-registro-mestre-validate.yml`
- `.github/workflows/ocue-maturidade-validate.yml`

Os workflows devem permanecer fail-closed: uma divergência entre percentual e evidência deve reprovar a execução, e não ser convertida em warning silencioso.

## Regra de atualização obrigatória

1. Criar ou alterar o artefato substantivo.
2. Executar/confirmar o validador específico aplicável.
3. Atualizar o `REGISTRO_MESTRE_EXECUCAO_v1_1.json` ou criar sua versão sucessora.
4. Confirmar o workflow do Registro Mestre em verde.
5. Recalcular a maturidade somente quando a evidência gerar crédito real em uma dimensão.
6. Criar novo snapshot de maturidade sem sobrescrever snapshots anteriores.
7. Não promover a branch para `main` enquanto houver gate institucional/pedagógico impeditivo.

## Regra contra perda de informação

Nenhum item do roadmap pode existir apenas na memória da equipe, em conversa de chat ou em arquivo isolado. Para ser considerado parte controlada do programa, precisa possuir um ID Pn-Dxx no Registro Mestre ou ser evidência expressamente vinculada a um desses IDs.

## Estado corrente da Fase 1

A Fase 1 possui 8 entregáveis e está em **78,90625% de conclusão interna**. Permanecem abertos:

- P1-D06 — concluir auditoria CRMG 2026 do N1/5º ano;
- P1-D07 — materializar a matriz explícita ODS × temas × direitos/deveres × Ciclo;
- P1-D08 — criar o glossário canônico;
- homologação curricular/pedagógica antes de promover para `main`.

O score global auditado da branch é **52,953125%** (52,95% para comunicação), na faixa de **Construção Instrucional**, ainda abaixo do próximo alvo de 55%.
