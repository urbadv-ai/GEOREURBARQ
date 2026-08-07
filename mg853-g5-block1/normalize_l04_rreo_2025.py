from __future__ import annotations

import concurrent.futures
import gzip
import hashlib
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT=Path('mg853-g5-block1/normalized/G5-L04_2025')
RAW=ROOT/'00_SUBSNAPSHOT_RREO_2025'; OUT=ROOT/'01_BASE_NORMALIZADA'; AUD=ROOT/'02_AUDITORIA'
for p in (RAW,OUT,AUD): p.mkdir(parents=True,exist_ok=True)
BASE='https://apidatalake.tesouro.gov.br/ords/cdwhprd/siconfi/tt'
YEAR=2025
retry=Retry(total=5,connect=5,read=4,status=4,backoff_factor=1.2,status_forcelist=(429,500,502,503,504),allowed_methods=frozenset({'GET'}),raise_on_status=False)

def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def sha(p:Path):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def session():
 s=requests.Session(); s.headers.update({'User-Agent':'MG853-G5-OABMG/3.0 (+auditoria oficial; consumo moderado)'})
 s.mount('https://',HTTPAdapter(max_retries=retry,pool_connections=2,pool_maxsize=2)); return s

def get_json(s,url,params):
 r=s.get(url,params=params,timeout=(20,120)); r.raise_for_status(); return r.json(),r.url

def get_entes():
 s=session(); j,u=get_json(s,BASE+'/entes',{'limit':5000})
 rows=[x for x in j.get('items',[]) if str(x.get('uf','')).upper()=='MG' and str(x.get('esfera','')).upper()=='M']
 df=pd.DataFrame(rows); df['cod_ibge_7']=df['cod_ibge'].astype(str).str.zfill(7); df=df.sort_values('cod_ibge_7').drop_duplicates('cod_ibge_7')
 assert len(df)==853, len(df)
 (RAW/'entes_mg.json').write_text(json.dumps(j,ensure_ascii=False,indent=2),encoding='utf-8')
 return df[['cod_ibge_7','ente','populacao']].rename(columns={'ente':'municipio','populacao':'populacao_siconfi'}),u

def select_value(items, *, anexo, cod_conta=None, conta=None, rotulo=None, coluna=None):
 vals=[]
 for x in items:
  if anexo and x.get('anexo')!=anexo: continue
  if cod_conta and x.get('cod_conta')!=cod_conta: continue
  if conta and str(x.get('conta','')).strip().casefold()!=conta.casefold(): continue
  if rotulo and str(x.get('rotulo','')).strip().casefold()!=rotulo.casefold(): continue
  if coluna and str(x.get('coluna','')).strip().casefold()!=coluna.casefold(): continue
  try: vals.append(float(x.get('valor')))
  except (TypeError,ValueError): pass
 if not vals: return None
 # Duplicidade exata é tolerada apenas se valores coincidem.
 if max(vals)-min(vals)>0.005: return {'CONFLITO':vals}
 return vals[0]

METRICS={
 'receita_exceto_intra_realizada':dict(anexo='RREO-Anexo 01',cod_conta='ReceitasExcetoIntraOrcamentarias',coluna='Até o Bimestre (c)'),
 'despesa_exceto_intra_liquidada':dict(anexo='RREO-Anexo 01',cod_conta='DespesasExcetoIntraOrcamentarias',coluna='DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)'),
 'investimentos_liquidados':dict(anexo='RREO-Anexo 01',cod_conta='Investimentos',coluna='DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)'),
 'pessoal_encargos_liquidados':dict(anexo='RREO-Anexo 01',cod_conta='PessoalEEncargosSociais',coluna='DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)'),
 'urbanismo_liquidado':dict(anexo='RREO-Anexo 02',cod_conta='RREO2TotalDespesas',conta='Urbanismo',rotulo='Total das Despesas Exceto Intra-Orçamentárias',coluna='DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)'),
 'habitacao_liquidado':dict(anexo='RREO-Anexo 02',cod_conta='RREO2TotalDespesas',conta='Habitação',rotulo='Total das Despesas Exceto Intra-Orçamentárias',coluna='DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)'),
 'saneamento_liquidado':dict(anexo='RREO-Anexo 02',cod_conta='RREO2TotalDespesas',conta='Saneamento',rotulo='Total das Despesas Exceto Intra-Orçamentárias',coluna='DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)'),
 'gestao_ambiental_liquidado':dict(anexo='RREO-Anexo 02',cod_conta='RREO2TotalDespesas',conta='Gestão Ambiental',rotulo='Total das Despesas Exceto Intra-Orçamentárias',coluna='DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)'),
 'rcl_12m':dict(anexo='RREO-Anexo 03',cod_conta='RREO3ReceitaCorrenteLiquida',coluna='TOTAL (ÚLTIMOS 12 MESES)'),
}

def fetch_one(row):
 code=row['cod_ibge_7']; s=session(); errors=[]; chosen=None; j=None; final=None
 for demo in ['RREO','RREO Simplificado']:
  try:
   jj,u=get_json(s,BASE+'/rreo',{'an_exercicio':YEAR,'nr_periodo':6,'co_tipo_demonstrativo':demo,'id_ente':code,'limit':5000})
   items=jj.get('items',[])
   # paginação defensiva
   if jj.get('hasMore'):
    offset=jj.get('limit',5000); allitems=list(items)
    while True:
     j2,_=get_json(s,BASE+'/rreo',{'an_exercicio':YEAR,'nr_periodo':6,'co_tipo_demonstrativo':demo,'id_ente':code,'limit':5000,'offset':offset})
     allitems.extend(j2.get('items',[]))
     if not j2.get('hasMore'): break
     offset += j2.get('limit',5000)
    jj['items']=allitems; jj['count']=len(allitems); items=allitems
   if items:
    chosen=demo; j=jj; final=u; break
  except Exception as e: errors.append(f'{demo}:{type(e).__name__}:{e}')
 if j is None:
  return {'cod_ibge_7':code,'municipio':row['municipio'],'populacao_siconfi':row['populacao_siconfi'],'status_cobertura':'ND_SEM_RREO_LOCALIZADO','demonstrativo':None,'itens':0,'errors':' | '.join(errors)}
 # congelar resposta oficial antes de extração
 raw=RAW/f'rreo_{YEAR}_{code}_{chosen.replace(" ","_")}.json.gz'
 payload=json.dumps(j,ensure_ascii=False,separators=(',',':')).encode('utf-8')
 with gzip.open(raw,'wb',compresslevel=9) as f: f.write(payload)
 rec={'cod_ibge_7':code,'municipio':row['municipio'],'populacao_siconfi':row['populacao_siconfi'],'status_cobertura':'OK','demonstrativo':chosen,'itens':len(j.get('items',[])),'raw_file':raw.name,'raw_sha256':sha(raw),'raw_url_final':final,'errors':' | '.join(errors)}
 conflicts=[]
 for name,sel in METRICS.items():
  v=select_value(j['items'],**sel)
  if isinstance(v,dict): conflicts.append(name); rec[name]=None
  else: rec[name]=v
 rec['conflitos_metricas']=';'.join(conflicts)
 return rec

entes,entes_url=get_entes(); rows=entes.to_dict(orient='records')
# Concorrência moderada; cada worker mantém sessão própria e retentativas.
results=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
 for i,r in enumerate(ex.map(fetch_one,rows),1):
  results.append(r)
  if i%100==0: print('PROGRESS',i,'/',len(rows),flush=True)

df=pd.DataFrame(results).sort_values('cod_ibge_7')
# Derivações somente quando denominador >0.
def ratio(n,d):
 n=pd.to_numeric(n,errors='coerce'); d=pd.to_numeric(d,errors='coerce'); return (100*n/d).where(d>0)
for n in ['investimentos_liquidados','urbanismo_liquidado','habitacao_liquidado','saneamento_liquidado','gestao_ambiental_liquidado']:
 df['pct_'+n+'_despesa']=ratio(df[n],df['despesa_exceto_intra_liquidada'])
df['pct_pessoal_orcamentario_rcl']=ratio(df['pessoal_encargos_liquidados'],df['rcl_12m'])
pop=pd.to_numeric(df['populacao_siconfi'],errors='coerce')
df['receita_exceto_intra_per_capita']=(pd.to_numeric(df['receita_exceto_intra_realizada'],errors='coerce')/pop).where(pop>0)
df['despesa_exceto_intra_per_capita']=(pd.to_numeric(df['despesa_exceto_intra_liquidada'],errors='coerce')/pop).where(pop>0)
df['ano_base']=YEAR; df['fonte_id']='F-016'; df['versao_transformacao']='G5-L04-NORM-2025-V0.1'; df['status_registro']=df['status_cobertura']; df['nivel_confianca']=df['status_cobertura'].map(lambda x:'ALTO_COM_RESSALVA_DECLARACAO_FISCAL' if x=='OK' else 'ND')
df.to_csv(OUT/'MG853_G5_L04_BASE_MUNICIPAL_RREO_2025_V0_1.csv',sep=';',index=False,encoding='utf-8-sig',decimal=',')
# long
metric_cols=list(METRICS)+[c for c in df.columns if c.startswith('pct_')]+['receita_exceto_intra_per_capita','despesa_exceto_intra_per_capita']
long=df.melt(id_vars=['cod_ibge_7','municipio','ano_base','fonte_id','status_cobertura','demonstrativo'],value_vars=metric_cols,var_name='indicador_id',value_name='valor')
long['status_valor']=long['valor'].apply(lambda x:'OK' if pd.notna(x) else 'ND')
long.to_csv(OUT/'MG853_G5_L04_INDICADORES_LONGOS_RREO_2025_V0_1.csv',sep=';',index=False,encoding='utf-8-sig',decimal=',')
# tests
T=[]
def t(i,n,res,exp,ok,obs=''): T.append({'teste_id':i,'teste':n,'resultado':str(res),'esperado':str(exp),'aprovado':'SIM' if ok else 'NAO','observacao':obs})
t('L04-25-T01','UNIVERSO_853',len(df),853,len(df)==853)
t('L04-25-T02','CHAVES_UNICAS',df.cod_ibge_7.nunique(),853,df.cod_ibge_7.nunique()==853)
t('L04-25-T03','CODIGO_7',df.cod_ibge_7.str.fullmatch(r'\d{7}').sum(),853,df.cod_ibge_7.str.fullmatch(r'\d{7}').all())
t('L04-25-T04','PREFIXO_31',df.cod_ibge_7.str.startswith('31').sum(),853,df.cod_ibge_7.str.startswith('31').all())
ok=df.status_cobertura.eq('OK').sum(); nd=853-ok
t('L04-25-T05','COBERTURA_RREO_2025',f'OK={ok};ND={nd}','documentar, não forçar 853 respondentes',True)
t('L04-25-T06','SEM_CONFLITO_METRICA',df.conflitos_metricas.fillna('').ne('').sum(),0,df.conflitos_metricas.fillna('').eq('').all())
# bounded derived percentages excluding personnel/RCL because different concept may legitimately exceed 100 only if odd; validate five functional/investment ratios.
bounded=[c for c in df.columns if c.startswith('pct_') and c!='pct_pessoal_orcamentario_rcl']
bad=0
for c in bounded:
 s=pd.to_numeric(df[c],errors='coerce').dropna(); bad+=int(((s<0)|(s>100)).sum())
t('L04-25-T07','PERCENTUAIS_DESPESA_0_100',bad,0,bad==0)
neg=0
for c in METRICS:
 s=pd.to_numeric(df[c],errors='coerce').dropna(); neg+=int((s<0).sum())
t('L04-25-T08','METRICAS_NUCLEO_NAO_NEGATIVAS',neg,0,neg==0,'Se falhar, preservar e auditar ocorrência oficial antes de qualquer tratamento.')
# directed sample: simply verify raw snapshot exists and selected values reproduce extractor for 12 codes
samples=[]; div=0
for code in ['3106200','3170206','3118601','3131703','3100203','3164308','3152105','3162922','3133303','3168606','3140001','3109006']:
 r=df[df.cod_ibge_7.eq(code)].iloc[0]
 if r.status_cobertura!='OK': samples.append({'cod_ibge_7':code,'municipio':r.municipio,'status':'ND','confere':'NA'}); continue
 raw=RAW/r.raw_file
 with gzip.open(raw,'rb') as f: jj=json.loads(f.read().decode('utf-8'))
 for name,sel in METRICS.items():
  exp=select_value(jj['items'],**sel); got=r[name]
  same=(exp is None and pd.isna(got)) or (not isinstance(exp,dict) and exp is not None and pd.notna(got) and abs(float(exp)-float(got))<0.005)
  div+=0 if same else 1; samples.append({'cod_ibge_7':code,'municipio':r.municipio,'indicador_id':name,'fonte':exp if not isinstance(exp,dict) else 'CONFLITO','normalizado':got,'confere':'SIM' if same else 'NAO'})
t('L04-25-T09','AMOSTRA_DIRIGIDA_REPRODUCAO',div,0,div==0,'12 municípios, somente declarantes verificados')
pd.DataFrame(T).to_csv(AUD/'MG853_G5_L04_TESTES_RREO_2025_V0_1.csv',sep=';',index=False,encoding='utf-8-sig')
pd.DataFrame(samples).to_csv(AUD/'MG853_G5_L04_AMOSTRA_RREO_2025_V0_1.csv',sep=';',index=False,encoding='utf-8-sig')
# dictionary
D=[]
for m,sel in METRICS.items(): D.append({'indicador_id':m,'origem':'RREO 6º bimestre 2025','seletor':json.dumps(sel,ensure_ascii=False),'unidade':'R$','denominador':'NA','uso':'NUCLEO_FISCAL','ressalva':'Valor declarado no SICONFI; ausência de declaração não equivale a zero.'})
for c in [x for x in df.columns if x.startswith('pct_')]: D.append({'indicador_id':c,'origem':'DERIVADO_G5','seletor':'formula versionada','unidade':'%','denominador':'despesa_exceto_intra_liquidada ou RCL conforme nome','uso':'NUCLEO_FISCAL','ressalva':'Não constitui indicador legal de limite fiscal salvo definição explícita.'})
pd.DataFrame(D).to_csv(OUT/'MG853_G5_L04_DICIONARIO_RREO_2025_V0_1.csv',sep=';',index=False,encoding='utf-8-sig')
summary={'lote':'G5-L04','fase':'2025_VALIDACAO_ESTADUAL','ano':YEAR,'data_hora_utc':now(),'municipios':853,'cobertura_ok':int(ok),'cobertura_nd':int(nd),'metricas_nucleo':len(METRICS),'indicadores_total':len(metric_cols),'testes_total':len(T),'testes_aprovados':sum(x['aprovado']=='SIM' for x in T),'status':'APROVADO_PARA_EXPANSAO_SERIE_2023_2025' if all(x['aprovado']=='SIM' for x in T) else 'BLOQUEADO_PARA_REVISAO','entes_url':entes_url}
(ROOT/'resumo_execucao.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
if summary['status'].startswith('BLOQUEADO'): raise SystemExit('Falha em teste local do painel 2025')
