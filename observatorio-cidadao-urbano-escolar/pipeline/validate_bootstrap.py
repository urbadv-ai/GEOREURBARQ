from __future__ import annotations
import csv,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; REPO=ROOT.parent
CFG=json.loads((ROOT/'config'/'ocue_config_v1_0.json').read_text(encoding='utf-8'))
SCHEMA=json.loads((ROOT/'schema'/'ocue_canonical_schema_v1_0.json').read_text(encoding='utf-8'))
def read_csv(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def columns(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return next(csv.reader(f))
errors=[]; checks={}; idsc_path=REPO/CFG['referencias_externas']['idsc_quality']
if not idsc_path.exists(): errors.append(f'IDSC quality file ausente: {idsc_path}')
else:
    q=json.loads(idsc_path.read_text(encoding='utf-8')); checks.update({'idsc_status':q.get('status_qualidade'),'idsc_br_municipios':q.get('municipios_nacionais_com_codigo_ibge_unico'),'idsc_mg_municipios':q.get('municipios_mg_com_idsc'),'idsc_br_ods_rows':q.get('linhas_ods_nacional')})
    if q.get('status_qualidade')!='APROVADO':errors.append('Base IDSC canônica não está APROVADA')
    if q.get('municipios_nacionais_com_codigo_ibge_unico')!=5570:errors.append('Base IDSC nacional não fecha 5570 municípios')
    if q.get('municipios_mg_com_idsc')!=853:errors.append('Recorte IDSC MG não fecha 853 municípios')
    if q.get('linhas_ods_nacional')!=94690:errors.append('Matriz nacional município×ODS não fecha 94.690 linhas')
ods=read_csv(ROOT/'catalogos'/'catalogo_ods_v1_0.csv'); nums=[int(r['ods_numero']) for r in ods]; checks['ods_catalog_count']=len(ods)
if nums!=list(range(1,18)):errors.append(f'Catálogo ODS inválido: {nums}')
ciclo=read_csv(ROOT/'catalogos'/'catalogo_ciclo_cidadania_urbana_v1_0.csv'); etapas=[r['etapa_codigo'] for r in ciclo]; checks['cycle_steps']=etapas
if etapas!=CFG['etapas_ciclo']:errors.append('Etapas do Ciclo divergem da configuração canônica')
for rel,key in [('catalogos/catalogo_temas_urbanos_v1_0.csv','tema_codigo'),('catalogos/catalogo_direitos_deveres_v1_0.csv','direito_dever_codigo'),('catalogos/catalogo_canais_participacao_v1_0.csv','canal_codigo')]:
    vals=[r[key] for r in read_csv(ROOT/rel)]; checks[f'{key}_count']=len(vals)
    if len(vals)!=len(set(vals)):errors.append(f'Duplicidade em {rel}:{key}')
for row in read_csv(ROOT/'catalogos'/'catalogo_temas_urbanos_v1_0.csv'):
    vals=[int(x) for x in row['ods_sugeridos'].split(';') if x]
    if any(x not in range(1,18) for x in vals):errors.append(f"ODS inválido no tema {row['tema_codigo']}")
prohibited={x.lower() for x in CFG['privacidade']['campos_proibidos']}
required={'observacoes.csv':{'observacao_id','cod_ibge_7','territorio_id','tema_codigo','etapa_ciclo_codigo','status_validacao'},'evidencias.csv':{'evidencia_id','observacao_id','status_privacidade','status_validacao'},'observacao_ods.csv':{'observacao_id','ods_numero','tipo_relacao','justificativa'},'participacoes.csv':{'participacao_id','observacao_id','canal_codigo','status'},'acompanhamentos.csv':{'acompanhamento_id','observacao_id','status_ocorrencia'}}
for p in sorted((ROOT/'templates').glob('*.csv')):
    cols=[c.strip() for c in columns(p)]; low={c.lower() for c in cols}; bad=sorted(low&prohibited)
    if bad:errors.append(f'Campos pessoais proibidos em {p.name}: {bad}')
    missing=sorted(required.get(p.name,set())-set(cols))
    if missing:errors.append(f'Campos obrigatórios ausentes em {p.name}: {missing}')
schema_txt=json.dumps(SCHEMA,ensure_ascii=False).lower()
for fld in prohibited:
    if f'"{fld}"' in schema_txt:errors.append(f'Schema contém campo pessoal proibido: {fld}')
sql=(ROOT/'database'/'schema_postgresql_postgis_v1_0.sql').read_text(encoding='utf-8').lower()
if 'geometry(multipolygon,4674)' not in sql or 'geometry(point,4674)' not in sql:errors.append('DDL não preserva SRID 4674 nas geometrias canônicas')
for fld in prohibited:
    if re.search(rf'\b{re.escape(fld)}\b\s+',sql):errors.append(f'DDL contém campo pessoal proibido: {fld}')
report={'dataset_id':CFG['dataset_id'],'schema_version':CFG['schema_version'],'status':'APROVADO' if not errors else 'REPROVADO','checks':checks,'errors':errors}
out=ROOT/'metadata'; out.mkdir(exist_ok=True); (out/'bootstrap_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(report,ensure_ascii=False,indent=2))
if errors:raise SystemExit(1)
