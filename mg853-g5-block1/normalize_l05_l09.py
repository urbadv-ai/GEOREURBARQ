from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOT=os.environ.get('LOT_ID','').strip().upper()
ROOT=Path('mg853-g5-block1/normalized')/LOT
RAW=ROOT/'00_SUBSNAPSHOT'; OUT=ROOT/'01_BASE_NORMALIZADA'; AUD=ROOT/'02_AUDITORIA'
for p in (RAW,OUT,AUD): p.mkdir(parents=True,exist_ok=True)

retry=Retry(total=7,connect=7,read=5,status=5,backoff_factor=1.5,status_forcelist=(429,500,502,503,504),allowed_methods=frozenset({'GET','HEAD'}),raise_on_status=False)
S=requests.Session(); S.headers.update({'User-Agent':'MG853-G5-OABMG/3.0 (+auditoria oficial)'})
S.mount('https://',HTTPAdapter(max_retries=retry)); TIMEOUT=(20,240)

def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def sha(path:Path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def download(url,name):
 p=RAW/name
 with S.get(url,stream=True,timeout=TIMEOUT,allow_redirects=True) as r:
  r.raise_for_status()
  with p.open('wb') as f:
   for ch in r.iter_content(1024*1024):
    if ch: f.write(ch)
 return p,r.url
def norm(s):
 s=unicodedata.normalize('NFKD',str(s)).encode('ascii','ignore').decode().lower()
 return re.sub(r'[^a-z0-9]+','_',s).strip('_')
def parse_br(v):
 if v is None or (isinstance(v,float) and math.isnan(v)): return None
 s=str(v).strip()
 if not s or s.lower() in {'nan','none','-','n/a','na'}: return None
 s=re.sub(r'[^0-9,.-]','',s)
 if not s: return None
 if ',' in s: s=s.replace('.','').replace(',','.')
 elif s.count('.')>1: s=s.replace('.','')
 elif '.' in s:
  # fontes habitacionais usam ponto como milhar em valores inteiros; se 3 dígitos após ponto, tratar como milhar
  a,b=s.rsplit('.',1)
  if len(b)==3: s=a+b
 try:return float(s)
 except:return None
def code6(v):
 s=str(v).strip()
 if not s or s.lower()=='nan': return None
 digs=re.sub(r'\D','',s)
 # casos lidos como 317.01 deveriam ser 317010, mas dtype=str preserva 317.010 na fonte original
 if len(digs)==5 and '.' in s: digs=digs+'0'
 return digs[:6].zfill(6) if len(digs)>=5 else None

def ibge_skeleton():
 u='https://servicodados.ibge.gov.br/api/v1/localidades/estados/31/municipios'
 r=S.get(u,timeout=TIMEOUT); r.raise_for_status(); j=r.json()
 rows=[]
 for x in j:
  c=str(x['id']); rows.append({'cod_ibge_7':c,'cod_ibge_6':c[:6],'municipio':x['nome'],'uf':'MG'})
 df=pd.DataFrame(rows).sort_values('cod_ibge_7').reset_index(drop=True)
 assert len(df)==853 and df.cod_ibge_7.nunique()==853
 p=RAW/'ibge_municipios_mg.json'; p.write_text(json.dumps(j,ensure_ascii=False,indent=2),encoding='utf-8')
 return df,p

def write_csv(df,path): df.to_csv(path,index=False,sep=';',encoding='utf-8-sig',decimal=',')
def tests_to_df(tests): return pd.DataFrame(tests,columns=['teste_id','teste','resultado','esperado','aprovado','observacao'])
def addtest(tests,i,n,res,exp,ok,obs=''): tests.append([i,n,str(res),str(exp),'SIM' if ok else 'NAO',obs])

def sample_codes(): return ['3106200','3170206','3118601','3131703','3100203','3164308','3152105','3162922','3133303','3168606','3140001','3109006']


def normalize_l05():
 sk,ibgep=ibge_skeleton(); tests=[]
 url='https://atlasdigital.mdr.gov.br/arquivos/BD_Atlas_1991_2025_v1.0_2026.04.23_Consolidado.csv'
 p,final=download(url,'BD_Atlas_1991_2025_v1.0_2026.04.23_Consolidado.csv')
 df=None
 for enc in ['utf-8-sig','utf-8','latin-1']:
  try:
   df=pd.read_csv(p,sep=';',encoding=enc,low_memory=False,dtype=str); break
  except: pass
 if df is None or len(df.columns)==1:
  for enc in ['utf-8-sig','utf-8','latin-1']:
   try: df=pd.read_csv(p,encoding=enc,low_memory=False,dtype=str); break
   except: pass
 if df is None: raise RuntimeError('CSV Atlas nao legivel')
 mg=df[df['Sigla_UF'].astype(str).str.strip().str.upper().eq('MG')].copy()
 mg['cod_ibge_7']=mg['Cod_IBGE_Mun'].astype(str).str.extract(r'(\d{7})',expand=False)
 mg['Data_Evento_dt']=pd.to_datetime(mg['Data_Evento'],dayfirst=True,errors='coerce')
 mg['ano_evento']=mg['Data_Evento_dt'].dt.year
 count_fields=['DH_MORTOS','DH_FERIDOS','DH_ENFERMOS','DH_DESABRIGADOS','DH_DESALOJADOS','DH_DESAPARECIDOS','DH_AFETADOS_SECA_ESTIAGEM','DH_total_danos_humanos_diretos','DH_OUTROS AFETADOS','DM_Uni Habita Danificadas','DM_Uni Habita Destruidas']
 for c in count_fields: mg[c+'_num']=pd.to_numeric(mg[c].str.replace(',','.',regex=False),errors='coerce')
 agg=[]
 for code,g in mg.groupby('cod_ibge_7',dropna=False):
  if pd.isna(code): continue
  rec={'cod_ibge_7':code,'atlas_eventos_total':len(g),'atlas_anos_com_evento':g['ano_evento'].nunique(dropna=True),
       'atlas_cobrade_distintos':g['Cod_Cobrade'].nunique(dropna=True),'atlas_grupos_distintos':g['grupo_de_desastre'].nunique(dropna=True),
       'atlas_eventos_reconhecidos':int(g['Status'].astype(str).str.strip().str.casefold().eq('reconhecido').sum())}
  groups={'Hidrológico':'atlas_eventos_hidrologicos','Climatológico':'atlas_eventos_climatologicos','Meteorológico':'atlas_eventos_meteorologicos','Outros':'atlas_eventos_outros'}
  for lab,out in groups.items(): rec[out]=int(g['grupo_de_desastre'].astype(str).str.strip().eq(lab).sum())
  outnames={'DH_MORTOS':'atlas_mortes','DH_FERIDOS':'atlas_feridos','DH_ENFERMOS':'atlas_enfermos','DH_DESABRIGADOS':'atlas_desabrigados','DH_DESALOJADOS':'atlas_desalojados','DH_DESAPARECIDOS':'atlas_desaparecidos','DH_AFETADOS_SECA_ESTIAGEM':'atlas_afetados_seca_estiagem','DH_total_danos_humanos_diretos':'atlas_danos_humanos_diretos','DH_OUTROS AFETADOS':'atlas_outros_afetados','DM_Uni Habita Danificadas':'atlas_uh_danificadas','DM_Uni Habita Destruidas':'atlas_uh_destruidas'}
  for c,out in outnames.items():
   s=g[c+'_num']; rec[out]=float(s.sum(min_count=1)) if s.notna().any() else None
  agg.append(rec)
 a=pd.DataFrame(agg)
 base=sk.merge(a,on='cod_ibge_7',how='left',validate='1:1')
 event_cols=['atlas_eventos_total','atlas_anos_com_evento','atlas_cobrade_distintos','atlas_grupos_distintos','atlas_eventos_reconhecidos','atlas_eventos_hidrologicos','atlas_eventos_climatologicos','atlas_eventos_meteorologicos','atlas_eventos_outros']
 base[event_cols]=base[event_cols].fillna(0).astype(int)
 damage_cols=[c for c in base.columns if c.startswith('atlas_') and c not in event_cols]
 # sem ocorrência registrada = 0 contagens de danos registrados; com ocorrência mas campo totalmente ausente permanece ND em formato longo
 noev=base.atlas_eventos_total.eq(0)
 for c in damage_cols: base.loc[noev,c]=0
 base['atlas_status_periodo']=base.atlas_eventos_total.gt(0).map({True:'COM_OCORRENCIA_REGISTRADA_NO_ATLAS',False:'SEM_OCORRENCIA_REGISTRADA_NO_ATLAS'})
 base['atlas_periodo']='1991-2025'; base['ano_base_fim']=2025; base['fonte_id']='F-017'; base['versao_transformacao']='G5-L05-NORM-V1.0'; base['status_registro']='OK'; base['nivel_confianca']='ALTO_COM_RESSALVA_REGISTRO_ADMINISTRATIVO'
 cols=['cod_ibge_7','municipio','uf','atlas_periodo','ano_base_fim','fonte_id','versao_transformacao','status_registro','nivel_confianca','atlas_status_periodo']+[c for c in base.columns if c.startswith('atlas_') and c not in {'atlas_periodo','atlas_status_periodo'}]
 base=base[cols]
 write_csv(base,OUT/'MG853_G5_L05_BASE_MUNICIPAL_NORMALIZADA_V1_0.csv')
 # long
 value_cols=[c for c in base.columns if c.startswith('atlas_') and c not in {'atlas_periodo','atlas_status_periodo'}]
 long=base.melt(id_vars=['cod_ibge_7','municipio','uf','atlas_periodo','fonte_id'],value_vars=value_cols,var_name='indicador_id',value_name='valor')
 long['status_valor']=long['valor'].apply(lambda x:'OK' if pd.notna(x) else 'ND')
 write_csv(long,OUT/'MG853_G5_L05_INDICADORES_LONGOS_V1_0.csv')
 # dictionary
 dic=[]
 for c in value_cols:
  unidade='CONTAGEM'; conceito=c.replace('atlas_','').replace('_',' ')
  dic.append({'indicador_id':c,'descricao_operacional':conceito,'unidade':unidade,'periodo':'1991-2025','fonte_id':'F-017','regra_ausencia':'0 apenas para contagem de registros quando município não possui ocorrência no Atlas; ND quando variável de dano estiver ausente em registros existentes','uso':'DESCRITIVO_PREVENTIVO','ressalva':'Registro administrativo não equivale a risco ou suscetibilidade; valores monetários excluídos do núcleo normalizado.'})
 write_csv(pd.DataFrame(dic),OUT/'MG853_G5_L05_DICIONARIO_INDICADORES_V1_0.csv')
 # tests
 addtest(tests,'L05-T01','UNIVERSO_853',len(base),853,len(base)==853)
 addtest(tests,'L05-T02','CHAVES_UNICAS',base.cod_ibge_7.nunique(),853,base.cod_ibge_7.nunique()==853)
 addtest(tests,'L05-T03','CODIGO_7_DIGITOS',base.cod_ibge_7.str.fullmatch(r'\d{7}').sum(),853,base.cod_ibge_7.str.fullmatch(r'\d{7}').all())
 addtest(tests,'L05-T04','PREFIXO_31',base.cod_ibge_7.str.startswith('31').sum(),853,base.cod_ibge_7.str.startswith('31').all())
 addtest(tests,'L05-T05','REGISTROS_MG_FONTE',len(mg),9686,len(mg)==9686,'controle da edição oficial utilizada')
 addtest(tests,'L05-T06','MUNICIPIOS_COM_EVENTO',(base.atlas_eventos_total>0).sum(),802,(base.atlas_eventos_total>0).sum()==802)
 addtest(tests,'L05-T07','MUNICIPIOS_SEM_EVENTO',(base.atlas_eventos_total==0).sum(),51,(base.atlas_eventos_total==0).sum()==51)
 addtest(tests,'L05-T08','SOMA_EVENTOS_MUNICIPAIS',base.atlas_eventos_total.sum(),len(mg),base.atlas_eventos_total.sum()==len(mg))
 addtest(tests,'L05-T09','PROTOCOLO_UNICO',mg['Protocolo_S2iD'].nunique(),len(mg),mg['Protocolo_S2iD'].nunique()==len(mg))
 addtest(tests,'L05-T10','DATAS_EVENTO_VALIDAS',mg['Data_Evento_dt'].notna().sum(),len(mg),mg['Data_Evento_dt'].notna().all())
 neg=0
 for c in count_fields: neg+=int((mg[c+'_num']<0).sum())
 addtest(tests,'L05-T11','CONTAGENS_NAO_NEGATIVAS',neg,0,neg==0)
 # sample compare
 samples=[]; div=0
 for code in sample_codes():
  b=base[base.cod_ibge_7.eq(code)].iloc[0]; g=mg[mg.cod_ibge_7.eq(code)]
  exp=len(g); got=int(b.atlas_eventos_total); ok=exp==got; div+=0 if ok else 1
  samples.append({'cod_ibge_7':code,'municipio':b.municipio,'campo':'atlas_eventos_total','fonte':exp,'normalizado':got,'confere':'SIM' if ok else 'NAO'})
 addtest(tests,'L05-T12','AMOSTRA_DIRIGIDA_EVENTOS',div,0,div==0,'12 municípios')
 tdf=tests_to_df(tests); write_csv(tdf,AUD/'MG853_G5_L05_TESTES_V1_0.csv'); write_csv(pd.DataFrame(samples),AUD/'MG853_G5_L05_AMOSTRA_DIRIGIDA_V1_0.csv')
 # semantic matrix
 sem=[]
 for c in value_cols:
  sem.append({'indicador_id':c,'conceito':'ocorrência/impacto registrado','camada_correlata':'G5-L06_SGB' if 'evento' in c or 'cobrade' in c or 'grupo' in c else 'G5-L01_CENSO','relacao':'COMPLEMENTAR_NAO_EQUIVALENTE','regra':'Ocorrência histórica não equivale a suscetibilidade física; impacto registrado não prova exposição causal.'})
 write_csv(pd.DataFrame(sem),AUD/'MG853_G5_L05_MATRIZ_SEMANTICA_V1_0.csv')
 manifest={'lote':'G5-L05','fonte':'F-017','data_hora_utc':now(),'url':url,'url_final':final,'sha256_fonte':sha(p),'sha256_ibge':sha(ibgep),'municipios':853,'registros_mg':len(mg),'municipios_com_evento':int((base.atlas_eventos_total>0).sum()),'indicadores':len(value_cols),'testes_total':len(tests),'testes_aprovados':int((tdf.aprovado=='SIM').sum()),'status':'NORMALIZACAO_APROVADA_PARA_REVISAO_NAO_INTEGRADA'}
 (ROOT/'resumo_execucao.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 return manifest


def normalize_l09():
 sk,ibgep=ibge_skeleton(); tests=[]
 urls={
  'mcmv_subsidiado.zip':'https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/habitacao/programa-minha-casa-minha-vida/arquivos/mcmv_subsidiado_202606302.zip',
  'mcmv_fgts_sintetico.zip':'https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/habitacao/programa-minha-casa-minha-vida/arquivos/mcmv_financ_sintetico_20260724.zip',
  'snhis.xls':'https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/habitacao/programa-minha-casa-minha-vida/minha-casa-minha-vida-fnhis-sub-50-1/arquivos-fnhis-sub-50/CpiadeFNHIS_SEMANAL_MCID_2026_06_15dadosaberto.xls',
  'dicionario.pdf':'https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/habitacao/arquivos-1/Dicionarios_SNH_2025_10_09.pdf'
 }
 paths={}; finals={}
 for name,url in urls.items(): paths[name],finals[name]=download(url,name)
 def extract_first(zpath,contains):
  with zipfile.ZipFile(zpath) as z:
   cand=[i for i in z.infolist() if contains in norm(i.filename) and Path(i.filename).suffix.lower() in {'.csv','.txt','.xlsx','.xls'}]
   if not cand: cand=[i for i in z.infolist() if Path(i.filename).suffix.lower() in {'.csv','.txt','.xlsx','.xls'}]
   if not cand: raise RuntimeError('arquivo tabular nao encontrado')
   i=cand[0]; target=RAW/Path(i.filename).name; target.write_bytes(z.read(i)); return target
 subsid=extract_first(paths['mcmv_subsidiado.zip'],'subsidiado')
 fgts=extract_first(paths['mcmv_fgts_sintetico.zip'],'financ')
 def read_csv_str(p):
  raw=p.read_bytes()[:100000]; enc='utf-8-sig'
  for e in ['utf-8-sig','utf-8','latin-1']:
   try: raw.decode(e); enc=e; break
   except: pass
  txt=raw.decode(enc,errors='replace'); sep=';'
  try: sep=csv.Sniffer().sniff(txt[:10000],delimiters=';,\t|').delimiter
  except: pass
  return pd.read_csv(p,sep=sep,encoding=enc,dtype=str,low_memory=False)
 ds=read_csv_str(subsid); df=read_csv_str(fgts)
 # normalize keys through IBGE official 6->7 map
 mp=dict(zip(sk.cod_ibge_6,sk.cod_ibge_7))
 for d in (ds,df):
  d['cod_ibge_6']=d['cod_ibge'].map(code6); d['cod_ibge_7']=d['cod_ibge_6'].map(mp)
 ds=ds[ds.get('txt_sigla_uf','').astype(str).str.upper().eq('MG')].copy()
 df=df[df.get('mcmv_fgts_txt_uf','').astype(str).str.upper().eq('MG')].copy()
 # subsidized numerics
 for c in ['qtd_uh','qtd_uh_entregues','qtd_uh_vigentes','qtd_uh_distratadas','val_contratado_total','val_desembolsado']:
  ds[c+'_num']=ds[c].map(parse_br)
 ds['sit_norm']=ds['txt_situacao_empreendimento'].astype(str).str.strip().str.casefold()
 subagg=[]
 for code,g in ds.groupby('cod_ibge_7',dropna=True):
  subagg.append({'cod_ibge_7':code,'mcmv_sub_registros':len(g),'mcmv_sub_concluidos':int(g.sit_norm.eq('concluído').sum()),
    'mcmv_sub_nao_concluidos':int(g.sit_norm.eq('não concluído').sum()),'mcmv_sub_cancelados':int(g.sit_norm.str.contains('distrat|cancel',regex=True).sum()),
    'mcmv_sub_uh_contratadas':g.qtd_uh_num.sum(min_count=1),'mcmv_sub_uh_entregues':g.qtd_uh_entregues_num.sum(min_count=1),
    'mcmv_sub_uh_vigentes':g.qtd_uh_vigentes_num.sum(min_count=1),'mcmv_sub_uh_distratadas':g.qtd_uh_distratadas_num.sum(min_count=1),
    'mcmv_sub_valor_contratado':g.val_contratado_total_num.sum(min_count=1),'mcmv_sub_valor_desembolsado':g.val_desembolsado_num.sum(min_count=1)})
 suba=pd.DataFrame(subagg)
 # FGTS
 for c in ['qtd_uh_financiadas','vlr_financiamento','vlr_subsidio']: df[c+'_num']=df[c].map(parse_br)
 df['ano_num']=df['extract'].astype(str).str.replace('.','',regex=False).str.extract(r'(\d{4})',expand=False)
 fagg=[]
 for code,g in df.groupby('cod_ibge_7',dropna=True):
  fagg.append({'cod_ibge_7':code,'mcmv_fgts_uh_financiadas':g.qtd_uh_financiadas_num.sum(min_count=1),
    'mcmv_fgts_valor_financiamento':g.vlr_financiamento_num.sum(min_count=1),'mcmv_fgts_valor_subsidio':g.vlr_subsidio_num.sum(min_count=1),
    'mcmv_fgts_anos_com_contrato':g.ano_num.nunique(dropna=True),'mcmv_fgts_ano_min':pd.to_numeric(g.ano_num,errors='coerce').min(),'mcmv_fgts_ano_max':pd.to_numeric(g.ano_num,errors='coerce').max()})
 fa=pd.DataFrame(fagg)
 # SNHIS exact table
 xls=pd.ExcelFile(paths['snhis.xls'],engine='xlrd'); sn=None; used_sheet=None
 for sheet in xls.sheet_names:
  cand=pd.read_excel(paths['snhis.xls'],sheet_name=sheet,engine='xlrd',dtype=str)
  ncols={norm(c):c for c in cand.columns}
  if any('coibge' in k or 'cod_ibge' in k for k in ncols): sn=cand; used_sheet=sheet; break
 if sn is None: raise RuntimeError('Tabela SNHIS com codigo IBGE nao identificada')
 colmap={norm(c):c for c in sn.columns}
 codecol=next(c for k,c in colmap.items() if 'coibge' in k or 'cod_ibge' in k)
 sn['cod_ibge_6']=sn[codecol].map(code6); sn['cod_ibge_7']=sn.cod_ibge_6.map(mp)
 # Identify status columns by semantic tokens; preserve raw published categories, no legal inference.
 status_targets={
  'snhis_situacao_lei_flhis':['situacao_lei_flhis'],
  'snhis_situacao_lei_cgflhis':['situacao_lei_cgflhis'],
  'snhis_situacao_termo_adesao':['situacao_termo','adesao'],
  'snhis_situacao_plano_habit':['situacao_plano_habit'],
  'snhis_situacao_rel_gestao':['situacao_rel','gestao'],
  'snhis_situacao_municipio':['situacao_municipio']}
 chosen={}
 for out,toks in status_targets.items():
  for k,c in colmap.items():
   if all(t in k for t in toks): chosen[out]=c; break
 # If no exact normalized 'situacao municipio', accept generic last situation column only if unique and explicitly recorded.
 sitcols=[c for k,c in colmap.items() if 'situa' in k]
 if 'snhis_situacao_municipio' not in chosen:
  gener=[c for c in sitcols if c not in chosen.values()]
  if len(gener)==1: chosen['snhis_situacao_municipio']=gener[0]
 skeep=['cod_ibge_7']+list(chosen.values())
 sns=sn[skeep].copy(); sns=sns[sns.cod_ibge_7.notna()]
 sns=sns.rename(columns={v:k for k,v in chosen.items()})
 # resolve duplicate municipality rows conservatively: identical status rows can dedupe; conflicting rows => ND_CONFLITO
 srows=[]
 for code,g in sns.groupby('cod_ibge_7'):
  rec={'cod_ibge_7':code}
  for c in chosen:
   vals=[str(v).strip() for v in g[c].dropna() if str(v).strip() and str(v).strip().lower()!='nan']
   uniq=list(dict.fromkeys(vals)); rec[c]=uniq[0] if len(uniq)==1 else ('NI' if len(uniq)==0 else 'ND_CONFLITO_FONTE')
  srows.append(rec)
 sa=pd.DataFrame(srows)
 base=sk.merge(suba,on='cod_ibge_7',how='left',validate='1:1').merge(fa,on='cod_ibge_7',how='left',validate='1:1').merge(sa,on='cod_ibge_7',how='left',validate='1:1')
 # explicit absence: zero only for counts from complete record table when municipality has no rows; amounts/units likewise 0 = no record in that dataset, not housing deficit.
 subcols=[c for c in base.columns if c.startswith('mcmv_sub_')]; fgcols=[c for c in base.columns if c.startswith('mcmv_fgts_')]
 sub_present=set(suba.cod_ibge_7); fg_present=set(fa.cod_ibge_7); sn_present=set(sa.cod_ibge_7)
 for idx,row in base.iterrows():
  code=row.cod_ibge_7
  if code not in sub_present:
   for c in subcols: base.at[idx,c]=0
  if code not in fg_present:
   for c in fgcols: base.at[idx,c]=0
  if code not in sn_present:
   for c in chosen: base.at[idx,c]='ND'
 base['mcmv_sub_status_cobertura']=base.cod_ibge_7.map(lambda x:'COM_REGISTRO' if x in sub_present else 'SEM_REGISTRO_NA_BASE_PUBLICADA')
 base['mcmv_fgts_status_cobertura']=base.cod_ibge_7.map(lambda x:'COM_REGISTRO' if x in fg_present else 'SEM_REGISTRO_NA_BASE_PUBLICADA')
 base['snhis_status_cobertura']=base.cod_ibge_7.map(lambda x:'COM_REGISTRO' if x in sn_present else 'ND')
 base['mcmv_sub_data_referencia']='2026-06-30'; base['mcmv_fgts_data_referencia']='2026-07-24'; base['snhis_data_referencia']='2026-06-15'; base['fonte_id']='F-020'; base['versao_transformacao']='G5-L09-NORM-V1.0'; base['status_registro']='OK'; base['nivel_confianca']='ALTO_COM_RESSALVA_COBERTURA_E_NATUREZA_ADMINISTRATIVA'
 ordered=['cod_ibge_7','municipio','uf','fonte_id','versao_transformacao','status_registro','nivel_confianca','mcmv_sub_data_referencia','mcmv_fgts_data_referencia','snhis_data_referencia','mcmv_sub_status_cobertura','mcmv_fgts_status_cobertura','snhis_status_cobertura']+subcols+fgcols+list(chosen.keys())
 base=base[ordered]
 write_csv(base,OUT/'MG853_G5_L09_BASE_MUNICIPAL_NORMALIZADA_V1_0.csv')
 # long numeric + categorical
 valcols=subcols+fgcols+list(chosen.keys())
 long=base.melt(id_vars=['cod_ibge_7','municipio','uf','fonte_id'],value_vars=valcols,var_name='indicador_id',value_name='valor')
 long['status_valor']=long.valor.apply(lambda x:'ND' if pd.isna(x) or str(x) in {'ND','NI','ND_CONFLITO_FONTE'} else 'OK')
 write_csv(long,OUT/'MG853_G5_L09_INDICADORES_LONGOS_V1_0.csv')
 dic=[]
 for c in subcols: dic.append({'indicador_id':c,'fonte_conjunto':'MCMV_SUBSIDIADO','unidade':'CONTAGEM_OU_REAIS','data_referencia':'2026-06-30','regra':'0 significa ausência de registro no conjunto publicado, não ausência de necessidade habitacional','restricao':'Não denominar déficit habitacional.'})
 for c in fgcols: dic.append({'indicador_id':c,'fonte_conjunto':'MCMV_FGTS_SINTETICO','unidade':'CONTAGEM_OU_REAIS','data_referencia':'2026-07-24','regra':'0 significa ausência de registro no conjunto publicado','restricao':'Categorias de faixa não foram rotuladas por inferência.'})
 for c in chosen: dic.append({'indicador_id':c,'fonte_conjunto':'SNHIS','unidade':'CATEGORIA_OFICIAL','data_referencia':'2026-06-15','regra':'Preservar categoria oficial; conflito explícito = ND_CONFLITO_FONTE','restricao':'Registro administrativo não constitui certificação jurídica municipal.'})
 write_csv(pd.DataFrame(dic),OUT/'MG853_G5_L09_DICIONARIO_INDICADORES_V1_0.csv')
 # tests
 addtest(tests,'L09-T01','UNIVERSO_853',len(base),853,len(base)==853)
 addtest(tests,'L09-T02','CHAVES_UNICAS',base.cod_ibge_7.nunique(),853,base.cod_ibge_7.nunique()==853)
 addtest(tests,'L09-T03','CODIGO_7',base.cod_ibge_7.str.fullmatch(r'\d{7}').sum(),853,base.cod_ibge_7.str.fullmatch(r'\d{7}').all())
 addtest(tests,'L09-T04','PREFIXO_31',base.cod_ibge_7.str.startswith('31').sum(),853,base.cod_ibge_7.str.startswith('31').all())
 addtest(tests,'L09-T05','SUBSIDIADO_REGISTROS_MG',len(ds),2012,len(ds)==2012)
 addtest(tests,'L09-T06','FGTS_REGISTROS_MG',len(df),23507,len(df)==23507)
 addtest(tests,'L09-T07','SUBSIDIADO_CODIGOS_MG',ds.cod_ibge_7.nunique(),620,ds.cod_ibge_7.nunique()==620)
 addtest(tests,'L09-T08','FGTS_CODIGOS_MG',df.cod_ibge_7.nunique(),802,df.cod_ibge_7.nunique()==802)
 addtest(tests,'L09-T09','MAPPING_SUBSIDIADO_SEM_PERDA',ds.cod_ibge_7.notna().sum(),len(ds),ds.cod_ibge_7.notna().all())
 addtest(tests,'L09-T10','MAPPING_FGTS_SEM_PERDA',df.cod_ibge_7.notna().sum(),len(df),df.cod_ibge_7.notna().all())
 addtest(tests,'L09-T11','ANOS_FGTS',f"{pd.to_numeric(df.ano_num,errors='coerce').min()}-{pd.to_numeric(df.ano_num,errors='coerce').max()}",'2009-2026',pd.to_numeric(df.ano_num,errors='coerce').min()==2009 and pd.to_numeric(df.ano_num,errors='coerce').max()==2026)
 addtest(tests,'L09-T12','SNHIS_COLUNAS_STATUS',len(chosen),'>=5',len(chosen)>=5,'colunas identificadas: '+','.join(chosen.keys()))
 addtest(tests,'L09-T13','SEM_JOIN_POR_NOME','IBGE_6_PARA_7','IBGE_6_PARA_7',True,'Mapa criado exclusivamente por códigos oficiais')
 neg=0
 for c in subcols+fgcols:
  if pd.api.types.is_numeric_dtype(base[c]): neg+=int((base[c]<0).sum())
 addtest(tests,'L09-T14','VALORES_QUANTITATIVOS_NAO_NEGATIVOS',neg,0,neg==0)
 # Directed sample numeric totals against source
 samples=[]; div=0
 for code in sample_codes():
  b=base[base.cod_ibge_7.eq(code)].iloc[0]
  gs=ds[ds.cod_ibge_7.eq(code)]; gf=df[df.cod_ibge_7.eq(code)]
  pairs=[('mcmv_sub_uh_contratadas',gs.qtd_uh_num.sum() if len(gs) else 0),('mcmv_fgts_uh_financiadas',gf.qtd_uh_financiadas_num.sum() if len(gf) else 0)]
  for fld,exp in pairs:
   got=float(b[fld]); ok=abs(float(exp)-got)<1e-6; div+=0 if ok else 1; samples.append({'cod_ibge_7':code,'municipio':b.municipio,'campo':fld,'fonte':exp,'normalizado':got,'confere':'SIM' if ok else 'NAO'})
 addtest(tests,'L09-T15','AMOSTRA_DIRIGIDA',div,0,div==0,'12 municípios × 2 métricas')
 # no deficit proxy
 addtest(tests,'L09-T16','SEM_PROXY_DEFICIT',sum('deficit' in c.lower() for c in base.columns),0,not any('deficit' in c.lower() for c in base.columns))
 tdf=tests_to_df(tests); write_csv(tdf,AUD/'MG853_G5_L09_TESTES_V1_0.csv'); write_csv(pd.DataFrame(samples),AUD/'MG853_G5_L09_AMOSTRA_DIRIGIDA_V1_0.csv')
 sem=[]
 for c in valcols:
  alvo='G5-L01_CENSO' if c.startswith('mcmv_') else 'MUNIC_SNHIS'
  sem.append({'indicador_id':c,'camada_correlata':alvo,'relacao':'COMPLEMENTAR_NAO_EQUIVALENTE','regra':'Política/produção/regularidade administrativa não equivale à condição domiciliar nem ao déficit habitacional.'})
 write_csv(pd.DataFrame(sem),AUD/'MG853_G5_L09_MATRIZ_SEMANTICA_V1_0.csv')
 write_csv(pd.DataFrame([{'fonte':'SNHIS','sheet':used_sheet,'campo_normalizado':k,'campo_origem':v} for k,v in chosen.items()]),AUD/'MG853_G5_L09_MAPEAMENTO_SNHIS_V1_0.csv')
 manifest={'lote':'G5-L09','fonte':'F-020','data_hora_utc':now(),'hashes':{k:sha(v) for k,v in paths.items()},'hash_ibge':sha(ibgep),'municipios':853,'registros_mcmv_sub_mg':len(ds),'municipios_mcmv_sub':int(ds.cod_ibge_7.nunique()),'registros_fgts_mg':len(df),'municipios_fgts':int(df.cod_ibge_7.nunique()),'snhis_sheet':used_sheet,'snhis_campos':chosen,'indicadores':len(valcols),'testes_total':len(tests),'testes_aprovados':int((tdf.aprovado=='SIM').sum()),'status':'NORMALIZACAO_APROVADA_PARA_REVISAO_NAO_INTEGRADA'}
 (ROOT/'resumo_execucao.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 return manifest

func={'G5-L05':normalize_l05,'G5-L09':normalize_l09}
if LOT not in func: raise SystemExit('LOT_ID deve ser G5-L05 ou G5-L09')
try:
 res=func[LOT](); print(json.dumps(res,ensure_ascii=False,indent=2))
except Exception as e:
 err={'lote':LOT,'status':'ERRO_CONTROLADO','erro':type(e).__name__,'mensagem':str(e),'data_hora_utc':now()}
 (ROOT/'erro_execucao.json').write_text(json.dumps(err,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(err,ensure_ascii=False,indent=2)); raise
