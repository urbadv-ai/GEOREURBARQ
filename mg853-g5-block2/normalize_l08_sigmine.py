from __future__ import annotations

import hashlib
import json
import math
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
import shapely
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT=Path('mg853-g5-block2/normalized/G5-L08')
RAW=ROOT/'00_SUBSNAPSHOT'; OUT=ROOT/'01_BASE_NORMALIZADA'; AUD=ROOT/'02_AUDITORIA'
for p in (RAW,OUT,AUD): p.mkdir(parents=True,exist_ok=True)
SIG_URL='https://dadosabertos.anm.gov.br/SIGMINE/PROCESSOS_MINERARIOS/MG.zip'
META_URL='https://dadosabertos.anm.gov.br/SIGMINE/metadados-sigmine.ods'
MUN_URL='https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_municipais/municipio_2025/UFs/MG/MG_Municipios_2025.zip'
AREA_CRS='EPSG:5880'
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

def unzip_shp(zpath,target):
 target.mkdir(parents=True,exist_ok=True)
 with zipfile.ZipFile(zpath) as z: z.extractall(target)
 shps=list(target.rglob('*.shp'))
 if not shps: raise RuntimeError(f'Nenhum SHP em {zpath}')
 return shps[0]

def csv(df,path): df.to_csv(path,index=False,sep=';',encoding='utf-8-sig',decimal=',')

sigzip,sigfinal=dl(SIG_URL,'SIGMINE_MG.zip'); metap,metafinal=dl(META_URL,'metadados-sigmine.ods'); munzip,munfinal=dl(MUN_URL,'MG_Municipios_2025.zip')
sigshp=unzip_shp(sigzip,RAW/'sigmine'); munshp=unzip_shp(munzip,RAW/'municipios')
src=gpd.read_file(sigshp); mun=gpd.read_file(munshp)
if str(src.crs).upper() not in {'EPSG:4674','SIRGAS 2000'} and getattr(src.crs,'to_epsg',lambda:None)()!=4674: raise RuntimeError(f'CRS SIGMINE inesperado {src.crs}')
if getattr(mun.crs,'to_epsg',lambda:None)()!=4674: mun=mun.to_crs(4674)
# municipality key discovery
code_candidates=[c for c in mun.columns if c.upper() in {'CD_MUN','CD_GEOCMU','CD_MUNICIP','CD_MUNICIPIO'} or ('CD_' in c.upper() and 'MUN' in c.upper())]
if not code_candidates: raise RuntimeError(f'Chave municipal não identificada: {list(mun.columns)}')
codecol=code_candidates[0]
name_candidates=[c for c in mun.columns if c.upper() in {'NM_MUN','NM_MUNICIP','NM_MUNICIPIO'} or ('NM_' in c.upper() and 'MUN' in c.upper())]
namecol=name_candidates[0] if name_candidates else None
mun['cod_ibge_7']=mun[codecol].astype(str).str.extract(r'(\d{7})',expand=False)
mun['municipio']=mun[namecol].astype(str) if namecol else ''
mun=mun[['cod_ibge_7','municipio','geometry']].drop_duplicates('cod_ibge_7')
if len(mun)!=853 or mun.cod_ibge_7.nunique()!=853: raise RuntimeError(f'Universo municipal {len(mun)}')

# Repair only invalid geometries in treated copy; original stays frozen.
src=src.reset_index(drop=True); src['_source_row']=src.index
invalid_before=(~src.geometry.is_valid) & src.geometry.notna(); invalid_ids=src.loc[invalid_before,'_source_row'].tolist()
src_area=src.to_crs(AREA_CRS); before_area=(src_area.geometry.area/10000).rename('area_ha_before')
repaired=src.geometry.copy()
repaired.loc[invalid_before]=repaired.loc[invalid_before].apply(shapely.make_valid)
src_t=src.copy(); src_t.geometry=repaired
invalid_after=(~src_t.geometry.is_valid) & src_t.geometry.notna()
after_area=(src_t.to_crs(AREA_CRS).geometry.area/10000).rename('area_ha_after')
rep=pd.DataFrame({'source_row':invalid_ids,'processo':src.loc[invalid_before,'PROCESSO'].astype(str).values if 'PROCESSO' in src.columns else '', 'area_ha_before':before_area.loc[invalid_before].values,'area_ha_after':after_area.loc[invalid_before].values})
if len(rep):
 rep['delta_ha']=rep.area_ha_after-rep.area_ha_before
 rep['delta_pct']=rep.apply(lambda r:(100*r.delta_ha/r.area_ha_before) if r.area_ha_before and not math.isclose(r.area_ha_before,0) else None,axis=1)
 rep['metodo']='shapely.make_valid'
 rep['valida_apos']=True
csv(rep,AUD/'MG853_G5_L08_AUDITORIA_REPAROS_GEOMETRICOS_V1_0.csv')
# Save repaired full layer for QGIS/reproduction.
src_t.to_file(OUT/'SIGMINE_MG_REPARADO_V1_0.gpkg',layer='sigmine_mg_reparado',driver='GPKG')

# Spatial overlay in equal-area working CRS. Preserve source semantics separately from municipality.
sigp=src_t.to_crs(AREA_CRS); munp=mun.to_crs(AREA_CRS)
munp['area_malha_geometrica_ha']=munp.geometry.area/10000
pairs=gpd.sjoin(sigp,munp[['cod_ibge_7','municipio','geometry']],how='inner',predicate='intersects')
# remove zero-area touches after true intersection
right_geom=munp.geometry
intersections=[]
for idx,row in pairs.iterrows():
 geom=row.geometry.intersection(right_geom.loc[row['index_right']])
 if geom.is_empty: continue
 area=geom.area/10000
 if area<=0: continue
 intersections.append({'source_row':int(row['_source_row']),'cod_ibge_7':row['cod_ibge_7'],'municipio':row['municipio'],'PROCESSO':str(row.get('PROCESSO','')),'FASE':str(row.get('FASE','')),'SUBS':str(row.get('SUBS','')),'USO':str(row.get('USO','')),'area_intersecao_ha':float(area),'geometry':geom})
inter=gpd.GeoDataFrame(intersections,geometry='geometry',crs=AREA_CRS)
if len(inter)==0: raise RuntimeError('Nenhuma interseção espacial encontrada')
# Municipal summary with gross overlap and dissolved unique area.
rows=[]
for _,mrow in munp.iterrows():
 code=mrow.cod_ibge_7; g=inter[inter.cod_ibge_7.eq(code)]
 if len(g):
  union=shapely.union_all(g.geometry.array); unique_ha=union.area/10000; gross=float(g.area_intersecao_ha.sum())
  rows.append({'cod_ibge_7':code,'municipio':mrow.municipio,'anm_presenca':1,'anm_processos_unicos':int(g.PROCESSO.nunique()),'anm_feicoes_intersectantes':int(g.source_row.nunique()),'anm_fases_distintas':int(g.FASE.replace('nan','').replace('',pd.NA).nunique(dropna=True)),'anm_substancias_distintas':int(g.SUBS.replace('nan','').replace('',pd.NA).nunique(dropna=True)),'anm_area_bruta_sobreposta_ha':gross,'anm_area_unica_ha':float(unique_ha),'area_malha_geometrica_ha':float(mrow.area_malha_geometrica_ha),'anm_pct_area_unica_malha_geometrica':float(100*unique_ha/mrow.area_malha_geometrica_ha) if mrow.area_malha_geometrica_ha>0 else None})
 else:
  rows.append({'cod_ibge_7':code,'municipio':mrow.municipio,'anm_presenca':0,'anm_processos_unicos':0,'anm_feicoes_intersectantes':0,'anm_fases_distintas':0,'anm_substancias_distintas':0,'anm_area_bruta_sobreposta_ha':0.0,'anm_area_unica_ha':0.0,'area_malha_geometrica_ha':float(mrow.area_malha_geometrica_ha),'anm_pct_area_unica_malha_geometrica':0.0})
base=pd.DataFrame(rows).sort_values('cod_ibge_7'); base['fonte_id']='F-019'; base['ano_snapshot']=2026; base['data_extracao']=now(); base['versao_transformacao']='G5-L08-NORM-V1.0'; base['status_registro']='OK'; base['nivel_confianca']='ALTO_COM_RESSALVA_CONTEXTO_TERRITORIAL'; base['observacao_auditoria']='Área percentual calculada provisoriamente sobre geometria da Malha Municipal Digital 2025; integração final poderá substituir denominador por AR_MUN_2025 sem alterar áreas de interseção.'
csv(base,OUT/'MG853_G5_L08_BASE_MUNICIPAL_NORMALIZADA_V1_0.csv')
# Long phase/substance counts for later analytical use without exploding base wide.
phase=inter.groupby(['cod_ibge_7','FASE'],dropna=False).agg(processos_unicos=('PROCESSO','nunique'),area_bruta_ha=('area_intersecao_ha','sum')).reset_index(); csv(phase,OUT/'MG853_G5_L08_FASES_LONGO_V1_0.csv')
subs=inter.groupby(['cod_ibge_7','SUBS'],dropna=False).agg(processos_unicos=('PROCESSO','nunique'),area_bruta_ha=('area_intersecao_ha','sum')).reset_index(); csv(subs,OUT/'MG853_G5_L08_SUBSTANCIAS_LONGO_V1_0.csv')
# Tests
T=[]
def t(i,n,res,exp,ok,obs=''): T.append({'teste_id':i,'teste':n,'resultado':str(res),'esperado':str(exp),'aprovado':'SIM' if ok else 'NAO','observacao':obs})
t('L08-T01','UNIVERSO_MUNICIPAL',len(base),853,len(base)==853)
t('L08-T02','CHAVES_UNICAS',base.cod_ibge_7.nunique(),853,base.cod_ibge_7.nunique()==853)
t('L08-T03','CRS_FONTE',src.crs.to_epsg(),4674,src.crs.to_epsg()==4674)
t('L08-T04','CRS_MALHA_IBGE',mun.crs.to_epsg(),4674,mun.crs.to_epsg()==4674)
t('L08-T05','GEOMETRIAS_INVALIDAS_ANTES',int(invalid_before.sum()),'documentado',True,'Quantidade depende do snapshot diário')
t('L08-T06','GEOMETRIAS_INVALIDAS_APOS',int(invalid_after.sum()),0,int(invalid_after.sum())==0)
max_delta=float(rep.delta_pct.abs().max()) if len(rep) and rep.delta_pct.notna().any() else 0.0
t('L08-T07','REPAROS_AUDITADOS',len(rep),int(invalid_before.sum()),len(rep)==int(invalid_before.sum()),f'max |delta área| % = {max_delta}')
neg=int((base[['anm_area_bruta_sobreposta_ha','anm_area_unica_ha']]<0).sum().sum()); t('L08-T08','AREAS_NAO_NEGATIVAS',neg,0,neg==0)
viol=int((base.anm_area_unica_ha-base.anm_area_bruta_sobreposta_ha>1e-6).sum()); t('L08-T09','AREA_UNICA_MENOR_OU_IGUAL_BRUTA',viol,0,viol==0)
viol2=int((base.anm_area_unica_ha-base.area_malha_geometrica_ha>0.01).sum()); t('L08-T10','AREA_UNICA_NAO_EXCEDE_MUNICIPIO',viol2,0,viol2==0)
pctbad=int(((base.anm_pct_area_unica_malha_geometrica<0)|(base.anm_pct_area_unica_malha_geometrica>100.0001)).sum()); t('L08-T11','PERCENTUAL_GEOMETRICO_0_100',pctbad,0,pctbad==0)
# sample 12 vs intersection table
sample_codes=['3106200','3170206','3118601','3131703','3100203','3164308','3152105','3162922','3133303','3168606','3140001','3109006']; samples=[]; div=0
for code in sample_codes:
 b=base[base.cod_ibge_7.eq(code)].iloc[0]; g=inter[inter.cod_ibge_7.eq(code)]; exp=g.PROCESSO.nunique(); got=b.anm_processos_unicos; same=int(exp)==int(got); div+=0 if same else 1; samples.append({'cod_ibge_7':code,'municipio':b.municipio,'processos_intersecao':int(exp),'processos_normalizado':int(got),'confere':'SIM' if same else 'NAO'})
t('L08-T12','AMOSTRA_DIRIGIDA_PROCESSOS',div,0,div==0)
pd.DataFrame(T).to_csv(AUD/'MG853_G5_L08_TESTES_V1_0.csv',sep=';',index=False,encoding='utf-8-sig'); pd.DataFrame(samples).to_csv(AUD/'MG853_G5_L08_AMOSTRA_DIRIGIDA_V1_0.csv',sep=';',index=False,encoding='utf-8-sig')
# Dictionary and semantic rule
D=[
 {'indicador_id':'anm_presenca','unidade':'0/1','descricao':'Existência de ao menos uma área de processo SIGMINE intersectando o município','restricao':'Presença não implica titularidade válida, ilegalidade, dano ambiental ou atividade em operação.'},
 {'indicador_id':'anm_processos_unicos','unidade':'contagem','descricao':'Processos únicos intersectantes','restricao':'Um processo pode ter múltiplas feições.'},
 {'indicador_id':'anm_feicoes_intersectantes','unidade':'contagem','descricao':'Feições fonte distintas intersectantes','restricao':'Não confundir feição com processo.'},
 {'indicador_id':'anm_area_bruta_sobreposta_ha','unidade':'ha','descricao':'Soma das áreas de interseção por feição/processo, admitindo sobreposição','restricao':'Pode conter dupla contagem espacial.'},
 {'indicador_id':'anm_area_unica_ha','unidade':'ha','descricao':'União espacial das áreas intersectantes dentro do município','restricao':'Elimina dupla contagem geométrica para medida territorial.'},
 {'indicador_id':'anm_pct_area_unica_malha_geometrica','unidade':'%','descricao':'Área única / área geométrica da Malha Municipal Digital 2025','restricao':'Indicador provisório de staging; denominador final será reconciliado com AR_MUN_2025 na integração.'}]
csv(pd.DataFrame(D),OUT/'MG853_G5_L08_DICIONARIO_INDICADORES_V1_0.csv')
summary={'lote':'G5-L08','fonte':'F-019','data_hora_utc':now(),'sha256_sigmine':sha(sigzip),'sha256_metadata':sha(metap),'sha256_malha_ibge_2025':sha(munzip),'feicoes_fonte':len(src),'processos_unicos_fonte':int(src.PROCESSO.nunique()) if 'PROCESSO' in src.columns else None,'invalidas_antes':int(invalid_before.sum()),'invalidas_apos':int(invalid_after.sum()),'intersecoes_com_area':len(inter),'municipios_com_presenca':int(base.anm_presenca.sum()),'testes_total':len(T),'testes_aprovados':sum(x['aprovado']=='SIM' for x in T),'status':'NORMALIZACAO_APROVADA_PARA_REVISAO_NAO_INTEGRADA' if all(x['aprovado']=='SIM' for x in T) else 'BLOQUEADO_PARA_REVISAO','crs_fonte':'EPSG:4674','crs_calculo_area':AREA_CRS,'regra':'Processo, feição, área bruta e área única permanecem conceitos distintos; nenhuma inferência jurídica ou ambiental é produzida.'}
(ROOT/'resumo_execucao.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(summary,ensure_ascii=False,indent=2))
if summary['status'].startswith('BLOQUEADO'): raise SystemExit('L08 bloqueado por QA geoespacial')
