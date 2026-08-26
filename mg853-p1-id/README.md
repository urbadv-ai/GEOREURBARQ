# IDSC-BR — camada canônica GEOREURBARQ

Esta pasta transforma a coleta temporária do **Índice de Desenvolvimento Sustentável das Cidades — Brasil (IDSC-BR)** em uma camada persistente, auditável e parametrizada para cruzamentos com a Base-Mestra MG-853.

## Aplicação institucional

A base passa a apoiar o **Programa Educacional para Cidades e Cidadania**, tendo como estrutura de observação territorial o **Observatório Cidadão Urbano Escolar** e como metodologia própria o **Ciclo de Cidadania Urbana**.

O IDSC é utilizado como **referência municipal** para contextualizar os 17 Objetivos de Desenvolvimento Sustentável. Ele não substitui nem autoriza inferências sobre bairros, escolas ou comunidades. O diagnóstico intramunicipal deve ser produzido em camada própria por evidências territoriais e participação cidadã.

## Regra canônica

A chave territorial é `cod_ibge_7`. A dimensão municipal do IBGE é a referência territorial. O pipeline detecta a chave por conteúdo e valida os códigos contra o IBGE; na estrutura atual do IDSC, o campo `id` corresponde ao próprio código IBGE de 7 dígitos.

A carga segue cinco camadas:

- `data/raw/current/`: respostas brutas integrais, persistidas em **gzip determinístico**;
- `data/normalized/`: base nacional IDSC, matriz nacional município × ODS e estruturas auxiliares;
- `data/mg853/`: recorte dos 853 municípios mineiros, resumo dos 17 ODS, detalhamento ODS e séries;
- `data/metadata/`: crosswalk IBGE, inventário de fontes, quality gates e manifestos SHA-256;
- `data/history/YYYY-MM-DD/`: snapshots do manifesto e da qualidade de cada carga aprovada.

A camada `source-wide` também é persistida em gzip, sem perda. A tabela `idsc_brasil_ods_long.csv` é analítica e não repete os longos textos de descrição em cada linha; esses textos permanecem integralmente preservados nas camadas raw e source-wide. Essa política evita redundância e respeita os limites de tamanho do GitHub sem perda de informação.

## Controles de qualidade

A atualização é **fail-closed**: qualquer divergência reprova a carga e impede a substituição da versão canônica válida. Os gates atuais exigem simultaneamente:

1. **5.570/5.570** municípios na dimensão IBGE;
2. **5.570/5.570** municípios IDSC vinculados por código IBGE;
3. **zero** registros nacionais sem código IBGE;
4. **5.570/5.570** municípios com os 17 ODS;
5. **94.690** relações município × ODS no Brasil (`5.570 × 17`);
6. **853/853** municípios mineiros no recorte;
7. **853/853** municípios mineiros vinculados ao IDSC;
8. **853/853** municípios mineiros com os 17 ODS;
9. **853/853** municípios com payload ODS detalhado;
10. **853/853** municípios com séries IDSC;
11. **zero** erros de detalhamento.

Os parâmetros ficam em `config/idsc_pipeline_config_v1_0.json` e o resultado de cada execução em `data/metadata/idsc_quality_checks.json`.

## Arquivos centrais

- `data/normalized/idsc_brasil_municipios.csv`: tabela nacional canônica, um município por linha;
- `data/normalized/idsc_brasil_ods_long.csv`: 17 ODS por município, em formato longo;
- `data/normalized/idsc_brasil_municipios_source_wide.csv.gz`: camada lossless de auditoria;
- `data/mg853/mg_853_idsc_municipios.csv`: recorte estadual de cobertura completa;
- `data/mg853/mg_853_idsc_ods_resumo_long.csv`: recorte MG da matriz município × ODS;
- `data/mg853/mg_853_idsc_ods_long.csv`: payload detalhado ODS em representação escalar longa;
- `data/mg853/mg_853_idsc_series_long.csv`: séries municipais em representação longa;
- `data/metadata/dataset_manifest.json`: relação dos artefatos aprovados, tamanhos e hashes;
- `data/metadata/raw_manifest.json`: URL, hash da resposta original, hash do gzip persistido e timestamp.

A especificação formal está em `schema/idsc_canonical_schema_v1_0.json`.

## Automação

O workflow `.github/workflows/mg853-p1-idhm-idsc.yml` executa a coleta mensalmente, sob acionamento manual e após alterações no pipeline/configuração. A sequência é:

**extrair → normalizar → validar → compactar camadas lossless → publicar artefato → validar política de tamanho → persistir no `main`.**

Execuções obsoletas são canceladas quando uma nova versão do pipeline é disparada, evitando concorrência entre snapshots.

## Fontes

- IDSC-BR / Instituto Cidades Sustentáveis: API pública utilizada pela aplicação do índice;
- IBGE SIDRA, tabela 4714: dimensão municipal e código IBGE usados como chave territorial.

Nenhuma carga é considerada canônica apenas por ter sido baixada: ela precisa superar integralmente os gates acima.
