from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT=Path('mg853-g5-block2/output/G5-L08')
RAW=ROOT/'00_SUBSNAPSHOT'; AUD=ROOT/'01_AUDITORIA'
for p in (RAW,AUD): p.mkdir(parents=True,exist_ok=True)
URL='https://dadosabertos.anm.gov.br/SIGMINE/PROCESSOS_MINERARIOS/MG.zip'
META='https://dadosabertos.anm.gov.br/SIGMINE/metadados-sigmine.ods'
retry=Retry(total=6,connect=6,read=5,status=5,backoff_factor=1.5,status_forcelist=(429,500,502,503,504),allowed_methods=frozenset({'GET'}),raise_on_status=False)
S=requests.Session(); S.headers.update({'User-Agent':'MG853-G5-OABMG/3.0 (+auditoria oficial)'})
S.mount('https://',HTTPAdapter(max_retries=retry))

def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def dl(url,name):
 p=RAW/name
 with S.get(url,stream=True,timeout=(20,300),allow_redirects=True) as r:
  r.raise_for_status()
  with p.open('wb') as f:
   for ch in r.iter_content(1024*1024):
    if ch: f.write(ch)
 return p,r.url

z,final=dl(URL,'SIGMINE_PROCESSOS_MINERARIOS_MG.zip')
m,metafinal=dl(META,'metadados-sigmine.ods')
with zipfile.ZipFile(z) as zz:
 files=[{'name':i.filename,'bytes':i.file_size,'compressed_bytes':i.compress_size} for i in zz.infolist() if not i.is_dir()]
 zz.extractall(RAW/'extracted')
shps=list((RAW/'extracted').rglob('*.shp'))
if not shps: raise RuntimeError('Nenhum SHP encontrado no pacote MG.zip')
reports=[]
for shp in shps:
 g=gpd.read_file(shp)
 geomtypes=g.geometry.geom_type.value_counts(dropna=False).to_dict()
 invalid=int((~g.geometry.is_valid & g.geometry.notna()).sum())
 empty=int(g.geometry.is_empty.sum())
 nullgeom=int(g.geometry.isna().sum())
 bounds=list(map(float,g.total_bounds)) if len(g) else []
 # duplicated process ids by likely process field, without assuming uniqueness semantics
 process_candidates=[c for c in g.columns if 'PROCESS' in c.upper() or 'NUMERO' in c.upper() or 'NUM'==c.upper()]
 duplicate_info={}
 for c in process_candidates[:5]:
  duplicate_info[c]={'unique':int(g[c].nunique(dropna=True)),'duplicated_rows':int(g[c].duplicated(keep=False).sum())}
 reports.append({'shp':str(shp.relative_to(RAW)),'rows':len(g),'columns':[str(c) for c in g.columns],'crs':str(g.crs),'geometry_types':geomtypes,'invalid_geometries':invalid,'empty_geometries':empty,'null_geometries':nullgeom,'bounds':bounds,'process_candidates':duplicate_info})
summary={'lote':'G5-L08','fonte':'F-019','data_hora_utc':now(),'url':URL,'url_final':final,'sha256_zip':sha(z),'bytes_zip':z.stat().st_size,'metadata_url_final':metafinal,'sha256_metadata':sha(m),'zip_files':files,'shapefiles':reports,'status':'STAGING_GEOESPACIAL_ESTRUTURAL_CONCLUIDO' if all(x['invalid_geometries']==0 and x['null_geometries']==0 for x in reports) else 'STAGING_COM_OCORRENCIAS_GEOMETRICAS'}
(AUD/'MG853_G5_L08_INVENTARIO_E_AUDITORIA_ESTRUTURAL_V1_0.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'status':summary['status'],'shapefiles':len(reports),'rows_total':sum(x['rows'] for x in reports),'crs':sorted(set(x['crs'] for x in reports)),'invalid_total':sum(x['invalid_geometries'] for x in reports),'nullgeom_total':sum(x['null_geometries'] for x in reports),'sha256_zip':summary['sha256_zip']},ensure_ascii=False,indent=2))
