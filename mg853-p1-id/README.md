# IDSC-BR — camada canônica GEOREURBARQ

Esta pasta transforma a coleta temporária do **Índice de Desenvolvimento Sustentável das Cidades — Brasil (IDSC-BR)** em uma camada persistente, auditável e parametrizada para cruzamentos com a Base-Mestra MG-853.

## Aplicação institucional

A base passa a apoiar o **Programa Educacional para Cidades e Cidadania**, tendo como estrutura de observação territorial o **Observatório Cidadão Urbano Escolar** e como metodologia própria o **Ciclo de Cidadania Urbana**.

O IDSC é utilizado como **referência municipal** para contextualizar os 17 Objetivos de Desenvolvimento Sustentável. Ele não substitui nem autoriza inferências sobre bairros, escolas ou comunidades. O diagnóstico intramunicipal deve ser produzido em camada própria por evidências territoriais e participação cidadã.

## Regra canônica

A chave territorial é `cod_ibge_7`. A lista de municípios do IBGE é a dimensão de referência; o recorte de Minas Gerais é derivado dos códigos iniciados por `31` e deve conter **exatamente 853 municípios**.

A carga segue cinco camadas:

- `data/raw/current/`: respostas brutas atuais das fontes, sem transformação semântica;
- `data/normalized/`: base nacional IDSC normalizada e estruturas auxiliares nacionais;
- `data/mg853/`: recorte mineiro, detalhamento ODS e séries em formato longo;
- `data/metadata/`: crosswalk IBGE, inventário das fontes, controles de qualidade e manifestos SHA-256;
- `data/history/YYYY-MM-DD/`: snapshots de manifesto e qualidade das cargas aprovadas.

O Git preserva o histórico completo dos arquivos `current` e `normalized`; a pasta `history` mantém a certificação lógica de cada carga aprovada sem duplicar desnecessariamente todas as bases.

## Controles de qualidade

A atualização é **fail-closed**. O pipeline encerra com erro e não promove uma nova carga quando algum dos gates canônicos falha. A versão 1.0 exige:

1. dimensão municipal IBGE nacional com pelo menos 5.500 códigos únicos;
2. base IDSC nacional com pelo menos 5.500 vínculos por código IBGE;
3. dimensão IBGE de Minas Gerais com exatamente 853 municípios;
4. recorte MG-IDSC com exatamente 853 municípios vinculados.

Os limites ficam parametrizados em `config/idsc_pipeline_config_v1_0.json`.

## Arquivos centrais

`data/normalized/idsc_brasil_municipios.csv` é a tabela nacional canônica. `data/normalized/idsc_brasil_municipios_source_wide.csv` preserva os campos expostos pela fonte para auditoria e evolução do mapeamento. `data/mg853/mg_853_idsc_municipios.csv` é o recorte mineiro de cobertura completa. Os payloads ODS e de evolução são convertidos para representação longa, preservando `json_path`, valor, hash do payload e URL de origem.

A especificação formal dos datasets está em `schema/idsc_canonical_schema_v1_0.json`.

## Automação

O workflow `.github/workflows/mg853-p1-idhm-idsc.yml` executa o pipeline em alterações estruturais, sob acionamento manual e mensalmente. Somente após a aprovação dos controles ele adiciona/atualiza `mg853-p1-id/data` no `main` e publica o mesmo conjunto como artefato temporário do GitHub Actions.

## Fontes

- IDSC-BR / Instituto Cidades Sustentáveis: API pública usada pela aplicação do índice;
- IBGE SIDRA, tabela 4714: dimensão municipal/código IBGE utilizada para a chave territorial.

Toda captura bruta recebe SHA-256 e timestamp UTC no manifesto de origem.
