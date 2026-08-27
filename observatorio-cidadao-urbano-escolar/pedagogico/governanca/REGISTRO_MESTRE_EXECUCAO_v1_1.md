# REGISTRO MESTRE DE EXECUÇÃO E RASTREABILIDADE — V1.1

## 1. Situação

Versão sucessora do `REGISTRO_MESTRE_EXECUCAO_v1_0.json`, criada após o primeiro gate de rastreabilidade detectar referências de evidência inexistentes. O erro não foi convertido em warning: os caminhos foram corrigidos e o crédito de artefatos inexistentes foi removido.

A fonte operacional é o JSON `REGISTRO_MESTRE_EXECUCAO_v1_1.json`.

## 2. Estrutura controlada

- 7 fases: P1 a P7;
- 64 entregáveis identificados por IDs permanentes `Pn-Dxx`;
- para cada entregável: status, fração de conclusão, evidências, gate e pendência;
- validação automática da existência dos caminhos de evidência quando há crédito de maturidade.

## 3. Fase 1 — Conteúdo curricular canônico

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

**Conclusão interna P1:** `(1 + 1 + 1 + 1 + 1 + 0,8125 + 0,5 + 0) / 8 = 78,90625%`.

## 4. Correções de rastreabilidade realizadas na V1.1

1. O nome presumido `arquitetura_unidades_integradoras_v1_0.json` foi substituído pelo arquivo real `pedagogico/conteudo/arquitetura_unidades_perfis_saida_v1_0.json`.
2. O arquivo presumido `PAP_OCUE_v1_0.md` não existe. P4-D01 agora utiliza, somente como evidência parcial, o `template_protocolo_aplicacao_escolar_v1_0.md` e o `PCPM_OCUE_PROTOCOLO_MESTRE_v1_0.md`.
3. Os modelos presumidos de consentimento, assentimento e ciência profissional não existem no repositório. P4-D05 voltou a **0% / NAO_INICIADO** até que documentos reais sejam produzidos e auditados.
4. A referência inexistente `formularios/especificacoes/` foi substituída pelos templates CSV reais do OCUE (`observacoes`, `evidencias`, `propostas`, `participacoes` e `acompanhamentos`).

## 5. Pendências críticas imediatas

- concluir auditoria CRMG 2026 do 3º trimestre do 5º ano para EF05GE10, EF05GE11 e EF05GE12;
- materializar a matriz canônica explícita ODS × temas × direitos/deveres × Ciclo;
- criar o glossário canônico;
- produzir a Sequência Didática Canônica N2 de 16 horas depois do fechamento curricular mínimo;
- criar e auditar os modelos de consentimento, assentimento e ciência profissional antes de qualquer piloto;
- manter `conteudo-programatico-v1` separada de `main` até o gate de homologação curricular/pedagógica.

## 6. Regra de governança

Um entregável só recebe crédito como `VERIFICADO` ou `PARCIAL_VERIFICADO` quando existe evidência versionada e, quando aplicável, gate automático correspondente. Pendência documentada é permitida; evidência inexistente é reprovada.
