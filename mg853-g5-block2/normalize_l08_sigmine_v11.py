from __future__ import annotations

import hashlib, json, math, zipfile
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
import shapely
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT=Path('mg853-g5-block2/normalized/G5-L08_V11')
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
def unzip_shp(zp,target):
 target.mkdir(parents=True,exist_ok=True)
 with zipfile.ZipFile(zp) as z:z.extractall(target)
 shps=list(target.rglob('*.shp'))
 if not shps: raise RuntimeError('SHP ausente')
 return shps[0]
def write_csv(df,p): df.to_csv(p,index=False,sep=';',encoding='utf-8-sig',decimal=',')

def audit_and_repair(gdf,label):
 g=gdf.reset_index(drop=True).copy(); g['_source_row']=g.index
 invalid=(~g.geometry.is_valid)&g.geometry.notna(); null=g.geometry.isna(); empty=g.geometry.is_empty
 # area original: force2d só para medição; não altera objeto bruto
 g2d=g.copy(); g2d.geometry=g2d.geometry.apply(lambda x: shapely.force_2d(x) if x is not None else None)
 before=g2d.to_crs(AREA_CRS).geometry.area/10000
 treated=g2d.copy()
 treated.loc[invalid,'geometry']=treated.loc[invalid,'geometry'].apply(shapely.make_valid)
 # make_valid pode gerar GeometryCollection; keep polygonal components by intersection with itself after force2d not enough.
 treated.geometry=treated.geometry.apply(lambda x: shapely.force_2d(x) if x is not None else None)
 invalid_after=(~treated.geometry.is_valid)&treated.geometry.notna()
 after=treated.to_crs(AREA_CRS).geometry.area/10000
 rows=[]
 for idx in g.index[invalid]:
  b=float(before.loc[idx]); a=float(after.loc[idx]); d=a-b
  rows.append({'dataset':label,'source_row':int(idx),'area_ha_before':b,'area_ha_after':a,'delta_ha':d,'delta_pct':(100*d/b if b else None),'metodo':'force_2d + shapely.make_valid','valida_apos':bool(treated.geometry.loc[idx].is_valid)})
 return treated,pd.DataFrame(rows),{'dataset':label,'rows':len(g),'invalid_before':int(invalid.sum()),'invalid_after':int(invalid_after.sum()),'null':int(null.sum()),'empty':int(empty.sum())}

sigzip,sigfinal=dl(SIG_URL,'SIGMINE_MG.zip'); meta,metafinal=dl(META_URL,'metadados-sigmine.ods'); munzip,munfinal=dl(MUN_URL,'MG_Municipios_2025.zip')
sig=gpd.read_file(unzip_shp(sigzip,RAW/'sigmine')); mun=gpd.read_file(unzip_shp(munzip,RAW/'municipios'))
if sig.crs.to_epsg()!=4674: raise RuntimeError(f'CRS SIGMINE {sig.crs}')
if mun.crs.to_epsg()!=4674: mun=mun.to_crs(4674)
code_candidates=[c for c in mun.columns if c.upper() in {'CD_MUN','CD_GEOCMU','CD_MUNICIP','CD_MUNICIPIO'} or ('CD_' in c.upper() and 'MUN' in c.upper())]
name_candidates=[c for c in mun.columns if c.upper() in {'NM_MUN','NM_MUNICIP','NM_MUNICIPIO'} or ('NM_' in c.upper() and 'MUN' in c.upper())]
if not code_candidates: raise RuntimeError('Chave municipal ausente')
mun['cod_ibge_7']=mun[code_candidates[0]].astype(str).str.extract(r'(\d{7})',expand=False); mun['municipio']=mun[name_candidates[0]].astype(str) if name_candidates else ''
mun=mun[['cod_ibge_7','municipio','geometry']].drop_duplicates('cod_ibge_7')
if len(mun)!=853 or mun.cod_ibge_7.nunique()!=853: raise RuntimeError(f'Malha municipal {len(mun)}')

sig_t,sig_rep,sig_aud=audit_and_repair(sig,'SIGMINE')
mun_t,mun_rep,mun_aud=audit_and_repair(mun,'IBGE_MALHA_2025')
rep=pd.concat([sig_rep,mun_rep],ignore_index=True); write_csv(rep,AUD/'MG853_G5_L08_AUDITORIA_REPAROS_GEOMETRICOS_V1_1.csv')
if sig_aud['invalid_after'] or mun_aud['invalid_after']: raise RuntimeError(f'Geometrias inválidas após reparo: {sig_aud} {mun_aud}')
sig_t.to_file(OUT/'SIGMINE_MG_REPARADO_2D_V1_1.gpkg',layer='sigmine_mg_reparado_2d',driver='GPKG')

sigp=sig_t.to_crs(AREA_CRS); munp=mun_t.to_crs(AREA_CRS); munp['area_malha_geometrica_ha']=munp.geometry.area/10000
pairs=gpd.sjoin(sigp,munp[['cod_ibge_7','municipio','geometry']],how='inner',predicate='intersects')
# Vectorized pairwise intersection after topology repair.
right=munp.geometry.reindex(pairs['index_right'].to_numpy()).reset_index(drop=True)
left=pairs.geometry.reset_index(drop=True)
igeom=shapely.intersection(left.array,right.array)
area=shapely.area(igeom)/10000
keep=(~shapely.is_empty(igeom)) & (area>0)
pairs2=pairs.reset_index(drop=True).loc[keep].copy(); pairs2['geometry']=igeom[keep]; pairs2['area_intersecao_ha']=area[keep]
inter=gpd.GeoDataFrame(pairs2,geometry='geometry',crs=AREA_CRS)

rows=[]
for _,m in munp.iterrows():
 g=inter[inter.cod_ibge_7.eq(m.cod_ibge_7)]
 if len(g):
  union=shapely.union_all(g.geometry.array); unique=float(shapely.area(union)/10000); gross=float(g.area_intersecao_ha.sum())
  rows.append({'cod_ibge_7':m.cod_ibge_7,'municipio':m.municipio,'anm_presenca':1,'anm_processos_unicos':int(g['PROCESSO'].nunique()) if 'PROCESSO' in g else 0,'anm_feicoes_intersectantes':int(g['_source_row'].nunique()),'anm_fases_distintas':int(g['FASE'].replace('',pd.NA).nunique(dropna=True)) if 'FASE' in g else 0,'anm_substancias_distintas':int(g['SUBS'].replace('',pd.NA).nunique(dropna=True)) if 'SUBS' in g else 0,'anm_area_bruta_sobreposta_ha':gross,'anm_area_unica_ha':unique,'area_malha_geometrica_ha':float(m.area_malha_geometrica_ha),'anm_pct_area_unica_malha_geometrica':100*unique/float(m.area_malha_geometrica_ha)})
 else:
  rows.append({'cod_ibge_7':m.cod_ibge_7,'municipio':m.municipio,'anm_presenca':0,'anm_processos_unicos':0,'anm_feicoes_intersectantes':0,'anm_fases_distintas':0,'anm_substancias_distintas':0,'anm_area_bruta_sobreposta_ha':0.0,'anm_area_unica_ha':0.0,'area_malha_geometrica_ha':float(m.area_malha_geometrica_ha),'anm_pct_area_unica_malha_geometrica':0.0})
base=pd.DataFrame(rows).sort_values('cod_ibge_7'); base['fonte_id']='F-019'; base['ano_snapshot']=2026; base['data_extracao']=now(); base['versao_transformacao']='G5-L08-NORM-V1.1'; base['status_registro']='OK'; base['nivel_confianca']='ALTO_COM_RESSALVA_CONTEXTO_TERRITORIAL'; base['observacao_auditoria']='Percentual provisório sobre geometria da Malha Municipal Digital 2025; denominador final será reconciliado com AR_MUN_2025 na integração.'
write_csv(base,OUT/'MG853_G5_L08_BASE_MUNICIPAL_NORMALIZADA_V1_1.csv')
# Long contextual categories
if 'FASE' in inter:
 phase=inter.groupby(['cod_ibge_7','FASE'],dropna=False).agg(processos_unicos=('PROCESSO','nunique'),area_bruta_ha=('area_intersecao_ha','sum')).reset_index(); write_csv(phase,OUT/'MG853_G5_L08_FASES_LONGO_V1_1.csv')
if 'SUBS' in inter:
 subs=inter.groupby(['cod_ibge_7','SUBS'],dropna=False).agg(processos_unicos=('PROCESSO','nunique'),area_bruta_ha=('area_intersecao_ha','sum')).reset_index(); write_csv(subs,OUT/'MG853_G5_L08_SUBSTANCIAS_LONGO_V1_1.csv')

T=[]
def t(i,n,r,e,ok,o=''):T.append({'teste_id':i,'teste':n,'resultado':str(r),'esperado':str(e),'aprovado':'SIM' if ok else 'NAO','observacao':o})
t('L08-T01','UNIVERSO_853',len(base),853,len(base)==853); t('L08-T02','CHAVES_UNICAS',base.cod_ibge_7.nunique(),853,base.cod_ibge_7.nunique()==853); t('L08-T03','CRS_SIGMINE',sig.crs.to_epsg(),4674,sig.crs.to_epsg()==4674); t('L08-T04','CRS_IBGE',mun.crs.to_epsg(),4674,mun.crs.to_epsg()==4674); t('L08-T05','INVALIDAS_SIGMINE_ANTES',sig_aud['invalid_before'],'documentado',True); t('L08-T06','INVALIDAS_SIGMINE_APOS',sig_aud['invalid_after'],0,sig_aud['invalid_after']==0); t('L08-T07','INVALIDAS_MALHA_ANTES',mun_aud['invalid_before'],'documentado',True); t('L08-T08','INVALIDAS_MALHA_APOS',mun_aud['invalid_after'],0,mun_aud['invalid_after']==0)
maxd=float(rep.delta_pct.abs().max()) if len(rep) and rep.delta_pct.notna().any() else 0;t('L08-T09','REPAROS_AUDITADOS',len(rep),sig_aud['invalid_before']+mun_aud['invalid_before'],len(rep)==sig_aud['invalid_before']+mun_aud['invalid_before'],f'max delta abs %={maxd}')
t('L08-T10','AREAS_NAO_NEGATIVAS',int((base[['anm_area_bruta_sobreposta_ha','anm_area_unica_ha']]<0).sum().sum()),0,not (base[['anm_area_bruta_sobreposta_ha','anm_area_unica_ha']]<0).any().any()); t('L08-T11','UNICA_LE_BRUTA',int((base.anm_area_unica_ha>base.anm_area_bruta_sobreposta_ha+1e-6).sum()),0,not (base.anm_area_unica_ha>base.anm_area_bruta_sobreposta_ha+1e-6).any()); t('L08-T12','PCT_0_100',int(((base.anm_pct_area_unica_malha_geometrica<0)|(base.anm_pct_area_unica_malha_geometrica>100.0001)).sum()),0,not ((base.anm_pct_area_unica_malha_geometrica<0)|(base.anm_pct_area_unica_malha_geometrica>100.0001)).any())
samples=[];div=0
for code in ['3106200','3170206','3118601','3131703','3100203','3164308','3152105','3162922','3133303','3168606','3140001','3109006']:
 b=base[base.cod_ibge_7.eq(code)].iloc[0];g=inter[inter.cod_ibge_7.eq(code)];exp=int(g['PROCESSO'].nunique()) if 'PROCESSO' in g else 0;got=int(b.anm_processos_unicos);same=exp==got;div+=0 if same else 1;samples.append({'cod_ibge_7':code,'municipio':b.municipio,'fonte_intersecao':exp,'normalizado':got,'confere':'SIM' if same else 'NAO'})
t('L08-T13','AMOSTRA_DIRIGIDA',div,0,div==0)
write_csv(pd.DataFrame(T),AUD/'MG853_G5_L08_TESTES_V1_1.csv');write_csv(pd.DataFrame(samples),AUD/'MG853_G5_L08_AMOSTRA_DIRIGIDA_V1_1.csv')
D=pd.DataFrame([
 {'indicador_id':'anm_presenca','unidade':'0/1','restricao':'Presença não implica regularidade, ilegalidade, dano ambiental ou atividade em operação.'},
 {'indicador_id':'anm_processos_unicos','unidade':'contagem','restricao':'Processo e feição são conceitos distintos.'},
 {'indicador_id':'anm_feicoes_intersectantes','unidade':'contagem','restricao':'Uma área/processo pode ser multipartido.'},
 {'indicador_id':'anm_area_bruta_sobreposta_ha','unidade':'ha','restricao':'Soma com sobreposição, pode duplicar espacialmente.'},
 {'indicador_id':'anm_area_unica_ha','unidade':'ha','restricao':'União espacial sem dupla contagem geométrica.'},
 {'indicador_id':'anm_pct_area_unica_malha_geometrica','unidade':'%','restricao':'Provisório; reconciliar denominador com AR_MUN_2025 na integração.'}]);write_csv(D,OUT/'MG853_G5_L08_DICIONARIO_INDICADORES_V1_1.csv')
summary={'lote':'G5-L08','fonte':'F-019','data_hora_utc':now(),'sha256_sigmine':sha(sigzip),'sha256_metadata':sha(meta),'sha256_malha_ibge_2025':sha(munzip),'feicoes_fonte':len(sig),'processos_unicos_fonte':int(sig.PROCESSO.nunique()) if 'PROCESSO' in sig else None,'sigmine_invalidas_antes':sig_aud['invalid_before'],'sigmine_invalidas_apos':sig_aud['invalid_after'],'malha_invalidas_antes':mun_aud['invalid_before'],'malha_invalidas_apos':mun_aud['invalid_after'],'intersecoes_com_area':len(inter),'municipios_com_presenca':int(base.anm_presenca.sum()),'testes_total':len(T),'testes_aprovados':sum(x['aprovado']=='SIM' for x in T),'status':'NORMALIZACAO_APROVADA_PARA_REVISAO_NAO_INTEGRADA' if all(x['aprovado']=='SIM' for x in T) else 'BLOQUEADO_PARA_REVISAO','crs_fonte':'EPSG:4674','crs_calculo_area':AREA_CRS,'transformacao_dimensional':'Measured/3D lido pela biblioteca e convertido explicitamente a 2D somente na cópia tratada para topologia e área; original ZIP preservado.'}
(ROOT/'resumo_execucao.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False,indent=2))
if summary['status'].startswith('BLOQUEADO'):raise SystemExit('L08 V1.1 bloqueado')
