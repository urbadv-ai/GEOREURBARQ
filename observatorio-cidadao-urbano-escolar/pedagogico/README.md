# Camada Pedagógica Canônica — OCUE

Esta pasta formaliza o processo de construção pedagógica e metodológica do **Programa Educacional para Cidades e Cidadania**, do conteúdo estruturante **Direitos e Deveres da Cidade**, do **Observatório Cidadão Urbano Escolar** e do **Ciclo de Cidadania Urbana**.

## Regra principal

Todo novo artefato pedagógico deve iniciar pelo `PCPM_OCUE_PROTOCOLO_MESTRE_v1_0.md` e percorrer os gates G0-G12. Nenhum template isolado é suficiente para aprovação.

## Fluxo canônico

`pesquisa normativa → enquadramento curricular → fundamentação → matriz de alinhamento → conteúdo programático → sequência didática → plano de aula/aplicação → avaliação → inclusão/privacidade → aprovação institucional → piloto → revisão → publicação`

## Arquitetura de escala

1. **Núcleo canônico nacional:** princípios, Ciclo, OCUE, ODS e conteúdo estruturante.
2. **Adaptador de rede:** BNCC + CNE + currículo/plano de curso/matriz da rede.
3. **Adaptador escolar/territorial:** PP/PPP, realidade local, calendário, recursos e aprovações.
4. **Instância de aplicação:** turma/grupo, execução, evidências, avaliação e acompanhamento.

Essa arquitetura evita criar versões independentes do projeto para cada município ou estado.

## Arquivos principais

- `config/pcpm_ocue_config_v1_0.json`: contrato parametrizado, gates, modos de inserção e regra de atualização.
- `normas/matriz_normativa_pedagogica_v1_0.json`: registro das bases legais, curriculares, orientativas, ABNT e Direito na Escola.
- `PCPM_OCUE_PROTOCOLO_MESTRE_v1_0.md`: procedimento obrigatório de construção e aplicação.
- `templates/template_conteudo_programatico_v1_0.md`: modelo mestre para programas/módulos.
- `templates/template_matriz_alinhamento_curricular_v1_0.csv`: ponte entre objetivo, BNCC, currículo da rede, TCT, ODS, OCUE e avaliação.
- `templates/template_sequencia_didatica_v1_0.md`: unidade/sequência didática.
- `templates/template_plano_aula_encontro_v1_0.md`: plano de aula/encontro.
- `templates/template_protocolo_aplicacao_escolar_v1_0.md`: PAP-OCUE para implantação em escola/rede.
- `templates/rubrica_validacao_pedagogica_v1_0.csv`: controle de qualidade com critérios críticos.
- `referencias/templates_publicos_catalogados_v1_0.md`: inventário das fontes públicas auditadas que fundamentaram os modelos.
- `pipeline/validate_pcpm_ocue.py`: validador fail-closed.

## Atualização normativa

A data-base normativa é registrada no config. A janela operacional padrão é de **90 dias**. O workflow mensal `OCUE Pedagogical Protocol Validation` reprova a estrutura quando a revisão normativa fica vencida, exigindo nova pesquisa documentada.

Mudança legislativa/curricular conhecida obriga revisão imediata, mesmo dentro dos 90 dias.

## Direito na Escola

As fontes públicas da OAB/MG e do Direito na Escola são tratadas como referenciais institucionais/pedagógicos. Materiais ou templates internos somente serão incorporados ao padrão canônico após acesso oficial, auditoria de conteúdo, comparação com os requisitos educacionais e versionamento.

## Regra ABNT

ABNT é utilizada como padrão interno para organização, citações, referências e apresentação técnico-científica. Não é tratada como substituta das normas curriculares ou como autorização de implantação escolar.
