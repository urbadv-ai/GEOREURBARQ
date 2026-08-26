-- Observatório Cidadão Urbano Escolar (OCUE) — schema canônico v1.0
-- PostgreSQL/PostGIS. Não armazena dados pessoais identificáveis de estudantes.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA IF NOT EXISTS ocue;

CREATE TABLE IF NOT EXISTS ocue.dim_escola (
  escola_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), cod_inep varchar(8), nome_escola text NOT NULL, rede_ensino text,
  cod_ibge_7 char(7) NOT NULL CHECK (cod_ibge_7 ~ '^[0-9]{7}$'), ativa boolean NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS ocue.dim_territorio (
  territorio_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), cod_ibge_7 char(7) NOT NULL CHECK (cod_ibge_7 ~ '^[0-9]{7}$'),
  tipo_territorio text NOT NULL CHECK (tipo_territorio IN ('BAIRRO','REGIAO','COMUNIDADE','ENTORNO_ESCOLAR','SETOR','OUTRO')),
  nome_territorio text NOT NULL, fonte_delimitacao text, status_validacao_territorio text NOT NULL DEFAULT 'INFORMADO', geom geometry(MultiPolygon,4674)
);
CREATE TABLE IF NOT EXISTS ocue.cat_tema_urbano (tema_codigo text PRIMARY KEY, tema_nome text NOT NULL, descricao_pedagogica text NOT NULL);
CREATE TABLE IF NOT EXISTS ocue.cat_ods (ods_numero smallint PRIMARY KEY CHECK (ods_numero BETWEEN 1 AND 17), ods_nome text NOT NULL);
CREATE TABLE IF NOT EXISTS ocue.cat_etapa_ciclo (ordem smallint UNIQUE NOT NULL CHECK (ordem BETWEEN 1 AND 7), etapa_codigo text PRIMARY KEY, etapa_nome text NOT NULL, pergunta_orientadora text NOT NULL);
CREATE TABLE IF NOT EXISTS ocue.cat_direito_dever (direito_dever_codigo text PRIMARY KEY, categoria_nome text NOT NULL, tipo_base text NOT NULL CHECK (tipo_base IN ('DIREITO','DEVER','AMBOS')), descricao_pedagogica text NOT NULL);
CREATE TABLE IF NOT EXISTS ocue.cat_canal_participacao (canal_codigo text PRIMARY KEY, canal_nome text NOT NULL, categoria text NOT NULL);
CREATE TABLE IF NOT EXISTS ocue.fato_observacao_urbana (
  observacao_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), cod_ibge_7 char(7) NOT NULL CHECK (cod_ibge_7 ~ '^[0-9]{7}$'),
  escola_id uuid REFERENCES ocue.dim_escola(escola_id), grupo_observador_id text, territorio_id uuid NOT NULL REFERENCES ocue.dim_territorio(territorio_id),
  tema_codigo text NOT NULL REFERENCES ocue.cat_tema_urbano(tema_codigo), titulo text NOT NULL, descricao text NOT NULL, data_observacao date NOT NULL,
  etapa_ciclo_codigo text NOT NULL REFERENCES ocue.cat_etapa_ciclo(etapa_codigo), nivel_impacto_percebido text CHECK (nivel_impacto_percebido IN ('BAIXO','MEDIO','ALTO','CRITICO')),
  abrangencia_percebida text CHECK (abrangencia_percebida IN ('PONTUAL','RUA','QUADRA','BAIRRO','REGIAO','MUNICIPAL')), status_validacao text NOT NULL DEFAULT 'REGISTRO_INICIAL',
  natureza_dado text NOT NULL DEFAULT 'DADO_CIDADAO_INTRAMUNICIPAL' CHECK (natureza_dado='DADO_CIDADAO_INTRAMUNICIPAL'), criado_em_utc timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ocue.fato_evidencia (
  evidencia_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), observacao_id uuid NOT NULL REFERENCES ocue.fato_observacao_urbana(observacao_id) ON DELETE CASCADE,
  tipo_evidencia text NOT NULL CHECK (tipo_evidencia IN ('FOTO','TEXTO','MAPA','MEDICAO','DOCUMENTO_PUBLICO','LINK_PUBLICO','OUTRO')), referencia text,
  sha256 char(64) CHECK (sha256 IS NULL OR sha256 ~ '^[a-f0-9]{64}$'), descricao text NOT NULL, data_evidencia date, geom geometry(Point,4674),
  status_privacidade text NOT NULL CHECK (status_privacidade IN ('SEM_PESSOAS_IDENTIFICAVEIS','ANONIMIZADA','USO_RESTRITO_AUTORIZADO','NAO_PUBLICAVEL')), status_validacao text NOT NULL DEFAULT 'REGISTRO_INICIAL'
);
CREATE TABLE IF NOT EXISTS ocue.rel_observacao_ods (observacao_id uuid NOT NULL REFERENCES ocue.fato_observacao_urbana(observacao_id) ON DELETE CASCADE, ods_numero smallint NOT NULL REFERENCES ocue.cat_ods(ods_numero), tipo_relacao text NOT NULL CHECK (tipo_relacao IN ('PRIMARIA','SECUNDARIA')), justificativa text NOT NULL CHECK (length(trim(justificativa)) > 0), PRIMARY KEY (observacao_id, ods_numero));
CREATE TABLE IF NOT EXISTS ocue.rel_observacao_direito_dever (observacao_id uuid NOT NULL REFERENCES ocue.fato_observacao_urbana(observacao_id) ON DELETE CASCADE, direito_dever_codigo text NOT NULL REFERENCES ocue.cat_direito_dever(direito_dever_codigo), perspectiva text NOT NULL CHECK (perspectiva IN ('DIREITO','DEVER','AMBOS')), justificativa text NOT NULL, status_validacao_juridica text NOT NULL DEFAULT 'NAO_ANALISADO' CHECK (status_validacao_juridica IN ('NAO_ANALISADO','PEDAGOGICO','VALIDADO_JURIDICAMENTE')), PRIMARY KEY (observacao_id, direito_dever_codigo));
CREATE TABLE IF NOT EXISTS ocue.fato_proposta (proposta_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), observacao_id uuid NOT NULL REFERENCES ocue.fato_observacao_urbana(observacao_id) ON DELETE CASCADE, descricao_proposta text NOT NULL, tipo_proposta text NOT NULL CHECK (tipo_proposta IN ('EDUCATIVA','COMUNITARIA','ADMINISTRATIVA','LEGISLATIVA','TECNICA','OUTRA')), data_proposta date NOT NULL, status_proposta text NOT NULL DEFAULT 'RASCUNHO');
CREATE TABLE IF NOT EXISTS ocue.fato_participacao (participacao_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), observacao_id uuid NOT NULL REFERENCES ocue.fato_observacao_urbana(observacao_id) ON DELETE CASCADE, proposta_id uuid REFERENCES ocue.fato_proposta(proposta_id), canal_codigo text NOT NULL REFERENCES ocue.cat_canal_participacao(canal_codigo), destinatario_categoria text NOT NULL, data_participacao date NOT NULL, protocolo_publico text, descricao text NOT NULL, status text NOT NULL DEFAULT 'REGISTRADO');
CREATE TABLE IF NOT EXISTS ocue.fato_acompanhamento (acompanhamento_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), observacao_id uuid NOT NULL REFERENCES ocue.fato_observacao_urbana(observacao_id) ON DELETE CASCADE, data_evento date NOT NULL, status_ocorrencia text NOT NULL CHECK (status_ocorrencia IN ('ABERTA','EM_ANALISE','ENCAMINHADA','EM_EXECUCAO','RESOLVIDA','PARCIALMENTE_RESOLVIDA','NAO_CONFIRMADA','ARQUIVADA')), descricao_evento text NOT NULL, fonte_evento text NOT NULL CHECK (fonte_evento IN ('CIDADA','ESCOLA','PODER_PUBLICO','DOCUMENTO_PUBLICO','OUTRA')), evidencia_id uuid REFERENCES ocue.fato_evidencia(evidencia_id));
CREATE INDEX IF NOT EXISTS idx_ocue_obs_cod_ibge ON ocue.fato_observacao_urbana(cod_ibge_7);
CREATE INDEX IF NOT EXISTS idx_ocue_obs_territorio ON ocue.fato_observacao_urbana(territorio_id);
CREATE INDEX IF NOT EXISTS idx_ocue_obs_tema ON ocue.fato_observacao_urbana(tema_codigo);
CREATE INDEX IF NOT EXISTS idx_ocue_territorio_geom ON ocue.dim_territorio USING gist(geom);
CREATE INDEX IF NOT EXISTS idx_ocue_evidencia_geom ON ocue.fato_evidencia USING gist(geom);
COMMENT ON SCHEMA ocue IS 'Observatório Cidadão Urbano Escolar — dados cidadãos intramunicipais; não confundir com indicadores oficiais municipais.';
COMMENT ON COLUMN ocue.fato_observacao_urbana.grupo_observador_id IS 'Identificador não pessoal de turma/grupo. Não registrar nome de estudante.';
