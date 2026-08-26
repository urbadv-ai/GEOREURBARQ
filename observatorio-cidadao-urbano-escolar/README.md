# Observatório Cidadão Urbano Escolar — camada canônica

O **Observatório Cidadão Urbano Escolar (OCUE)** é a camada intramunicipal do **Programa Educacional para Cidades e Cidadania**. Sua metodologia operacional é o **Ciclo de Cidadania Urbana**:

**CONHECER → OBSERVAR → MAPEAR → CLASSIFICAR → PROPOR → PARTICIPAR → ACOMPANHAR**

A finalidade desta pasta é transformar observações produzidas no ambiente escolar e comunitário em dados territoriais rastreáveis, comparáveis e reutilizáveis, sem confundir percepção cidadã com indicador oficial.

## Princípios de arquitetura

1. **Separação de escalas.** O IDSC-BR permanece referência municipal. O OCUE registra evidências intramunicipais em bairros, regiões, comunidades, entorno escolar ou outro território validado.
2. **Chave municipal canônica.** Todo território OCUE é vinculado ao município por `cod_ibge_7`.
3. **Normalização.** Ocorrência, evidência, ODS, direito/dever, proposta, participação e acompanhamento são entidades separadas.
4. **Rastreabilidade.** Evidências digitais podem receber SHA-256, URL/referência de origem e data de captura.
5. **Qualificação gradual.** Uma observação cidadã não se torna automaticamente “fato oficial”. O status de validação registra o nível de confirmação.
6. **Neutralidade institucional.** O banco registra problema, evidência, proposta, encaminhamento e resultado; não atribui responsabilidade jurídico-administrativa sem validação própria.
7. **Privacidade por desenho.** Não é necessário armazenar nome, CPF, e-mail, telefone ou outro identificador pessoal de estudante. Turmas e grupos podem ser representados por identificadores internos não pessoais.
8. **Interoperabilidade geográfica.** A camada de intercâmbio usa SIRGAS 2000 / EPSG:4674 para pontos e geometrias territoriais no Brasil, admitindo transformação posterior em QGIS/PostGIS.
9. **ODS como relação N:N.** Uma ocorrência pode se relacionar a vários ODS, sempre com justificativa.
10. **Dados oficiais e dados cidadãos não são fundidos semanticamente.** Eles podem ser cruzados por território, mantendo fonte, escala e natureza do dado.

## Estrutura

- `config/`: parâmetros institucionais, privacidade e regras de validação;
- `schema/`: contrato formal das entidades e relacionamentos;
- `catalogos/`: vocabulários controlados;
- `database/`: DDL PostgreSQL/PostGIS;
- `templates/`: cabeçalhos canônicos para importação/coleta;
- `pipeline/`: validação estrutural automatizada;
- `metadata/`: reservado para relatórios de validação e versões futuras.

## Relação com o IDSC-BR

O pipeline IDSC validado em `mg853-p1-id/` fornece o contexto municipal:

`cod_ibge_7 → município → pontuação IDSC → 17 ODS → séries`

O OCUE adiciona:

`cod_ibge_7 → território intramunicipal → escola/grupo → ocorrência → evidência → ODS → direito/dever → proposta → participação → acompanhamento`

A leitura combinada deve respeitar a escala: o desempenho municipal do IDSC **contextualiza**, mas não prova nem invalida uma ocorrência de bairro.

## Ciclo de Cidadania Urbana

Cada ocorrência pode avançar por sete etapas. O campo `etapa_ciclo_codigo` indica a etapa corrente, enquanto os eventos de proposta, participação e acompanhamento registram o histórico real. O ciclo não exige que toda ocorrência alcance a etapa 7; o banco deve preservar também casos arquivados, inconclusivos ou invalidados.

## Uso científico e educacional

A base foi desenhada para permitir, entre outros:

- mapa de problemas por bairro/região;
- frequência e distribuição territorial dos temas urbanos;
- associação de ocorrências aos 17 ODS;
- comparação entre percepção cidadã e indicadores públicos;
- histórico de propostas e encaminhamentos;
- taxa de resposta/solução por tipo de problema e canal de participação;
- atividades pedagógicas e avaliações de aprendizagem;
- produção de mapas, dashboards, relatórios e pesquisas científicas.

A especificação não substitui protocolo ético, política de imagens, validação pedagógica ou revisão jurídica quando a aplicação envolver crianças e adolescentes.
