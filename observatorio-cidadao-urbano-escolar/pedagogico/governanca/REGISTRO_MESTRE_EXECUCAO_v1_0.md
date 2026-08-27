# REGISTRO MESTRE DE EXECUÇÃO E RASTREABILIDADE — V1.0

## 1. Finalidade

Este documento é a visão humana do arquivo estruturado `REGISTRO_MESTRE_EXECUCAO_v1_0.json`. O JSON é a fonte operacional para validação automática; este Markdown é a leitura executiva.

Nenhum entregável do `ROADMAP_PONTO_FINAL_v1_0.md` deve ficar fora do Registro Mestre. Cada item possui ID, fase, status, fração de conclusão, evidência, gate e pendência.

## 2. Hierarquia de controle

1. `ROADMAP_PONTO_FINAL_v1_0.md` — define o ponto final, fases, marcos e gates.
2. `maturidade_projeto_v1_*.json` — snapshots imutáveis do percentual global.
3. `REGISTRO_MESTRE_EXECUCAO_v1_0.json` — ledger de todos os entregáveis do roadmap.
4. Artefatos canônicos versionados — conteúdo, matrizes, protocolos, instrumentos e materiais.
5. Validadores e GitHub Actions — comprovam integridade estrutural e gates automatizáveis.
6. Relatórios/artefatos de CI — comprovam cada execução de validação.

## 3. Status permitidos

- `NAO_INICIADO`: 0% do entregável.
- `EM_EXECUCAO`: trabalho iniciado, ainda sem base suficiente para crédito verificável.
- `PARCIAL_VERIFICADO`: possui evidência e fração explícita de conclusão.
- `VERIFICADO`: artefato versionado e gate aplicável satisfeito.
- `BLOQUEADO`: depende de gate ou fase anterior.

Pendência documentada não é erro. Falsa certeza é erro.

## 4. Posição atual da Fase 1

| ID | Entregável | Status | Fração |
|---|---|---|---:|
| P1-D01 | Conteúdo Programático V1.0 | VERIFICADO | 100% |
| P1-D02 | Eixos e módulos | VERIFICADO | 100% |
| P1-D03 | Progressão por faixa etária | VERIFICADO | 100% |
| P1-D04 | Resultados de aprendizagem | VERIFICADO | 100% |
| P1-D05 | Carga horária | VERIFICADO | 100% |
| P1-D06 | Matriz curricular BNCC + CRMG 2026 | PARCIAL_VERIFICADO | 81,25% |
| P1-D07 | Matriz ODS × temas × direitos/deveres × Ciclo | PARCIAL_VERIFICADO | 50% |
| P1-D08 | Glossário canônico | NAO_INICIADO | 0% |

**Conclusão interna da Fase 1: 78,90625%.**

Cálculo: `(1 + 1 + 1 + 1 + 1 + 0,8125 + 0,5 + 0) / 8 = 0,7890625`.

A Fase 1 não está encerrada enquanto P1-D06, P1-D07 e P1-D08 não forem resolvidos e o conteúdo não for homologado para `main`.

## 5. Pendências críticas imediatas

1. Auditar o Plano de Curso 2026 do 3º trimestre do 5º ano para EF05GE10, EF05GE11 e EF05GE12.
2. Materializar a matriz explícita e normalizada ODS × tema OCUE × direito/dever × etapa do Ciclo.
3. Criar o glossário canônico versionado.
4. Produzir e validar a Sequência Didática Canônica N2 de 16 horas.
5. Preservar `conteudo-programatico-v1` como branch de auditoria até a revisão curricular/pedagógica e promoção controlada ao `main`.

## 6. Próxima passagem de gate

O próximo alvo global do roadmap é **55%**, encerrando a Fase 1 e permitindo avanço seguro da construção instrucional. A simples existência de artefatos da Fase 2 não substitui o fechamento dos três pontos abertos da Fase 1.

## 7. Regra de atualização

Toda nova entrega deverá atualizar primeiro o JSON estruturado. O snapshot de maturidade só poderá ser alterado quando houver regra de cálculo reproduzível e evidência correspondente. Snapshots anteriores não são sobrescritos.
