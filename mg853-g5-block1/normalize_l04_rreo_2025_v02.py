from __future__ import annotations

import concurrent.futures
import gzip
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT=Path('mg853-g5-block1/normalized/G5-L04_2025_V02')
RAW=ROOT/'00_SUBSNAPSHOT_RREO_2025'; OUT=ROOT/'01_BASE_NORMALIZADA'; AUD=ROOT/'02_AUDITORIA'
for p in (RAW,OUT,AUD): p.mkdir(parents=True,exist_ok=True)
BASE='https://apidatalake.tesouro.gov.br/ords/cdwhprd/siconfi/tt'; YEAR=2025
retry=Retry(total=5,connect=5,read=4,status=4,backoff_factor=1.2,status_forcelist=(429,500,502,503,504),allowed_methods=frozenset({'GET'}),raise_on_status=False)

def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def ses():
 s=requests.Session(); s.headers.update({'User-Agent':'MG853-G5-OABMG/3.0 (+auditoria oficial; consumo moderado)'})
 s.mount('https://',HTTPAdapter(max_retries=retry,pool_connections=2,pool_maxsize=2)); return s

def getj(s,path,params):
 r=s.get(BASE+path,params=params,timeout=(20,120)); r.raise_for_status(); return r.json(),r.url

def pref_items(items):
 return [x for x in items if re.search(r'\bprefeitura\s+municipal\b',str(x.get('instituicao','')),re.I)]

def select(items, sel):
 ms=[]
 for x in items:
  if sel.get('anexo') and x.get('anexo')!=sel['anexo']: continue
  if sel.get('cod_conta') and x.get('cod_conta')!=sel['cod_conta']: continue
  if sel.get('conta') and str(x.get('conta','')).strip().casefold()!=sel['conta'].casefold(): continue
  if sel.get('rotulo') and str(x.get('rotulo','')).strip().casefold()!=sel['rotulo'].casefold(): continue
  if sel.get('coluna') and str(x.get('coluna','')).strip().casefold()!=sel['coluna'].casefold(): continue
  ms.append(x)
 vals=[]
 for x in ms:
  try: vals.append(float(x.get('valor')))
  except: pass
 if not vals: return None, ms
 if max(vals)-min(vals)>0.005: return {'CONFLITO':vals}, ms
 return vals[0],ms

M={
 'receita_exceto_intra_realizada':dict(anexo='RREO-Anexo 01',cod_conta='ReceitasExcetoIntraOrcamentarias',coluna='Até o Bimestre (c)'),
 'despesa_exceto_intra_liquidada':dict(anexo='RREO-Anexo 01',cod_conta='DespesasExcetoIntraOrcamentarias',coluna='DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)'),
 'investimentos_liquidados':dict(anexo='RREO-Anexo 01',cod_conta='Investimentos',coluna='DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)'),
 'pessoal_encargos_liquidados':dict(anexo='RREO-Anexo 01',cod_conta='PessoalEEncargosSociais',coluna='DESPESAS LIQUIDADAS ATÉ O BIMESTRE (h)'),
 'urbanismo_liquidado':dict(anexo='RREO-Anexo 02',cod_conta='RREO2TotalDespesas',conta='Urbanismo',rotulo='Total das Despesas Exceto Intra-Orçamentárias',coluna='DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)'),
 'habitacao_liquidado':dict(anexo='RREO-Anexo 02',cod_conta='RREO2TotalDespesas',conta='Habitação',rotulo='Total das Despesas Exceto Intra-Orçamentárias',coluna='DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)'),
 'saneamento_liquidado':dict(anexo='RREO-Anexo 02',cod_conta='RREO2TotalDespesas',conta='Saneamento',rotulo='Total das Despesas Exceto Intra-Orçamentárias',coluna='DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)'),
 'gestao_ambiental_liquidado':dict(anexo='RREO-Anexo 02',cod_conta='RREO2TotalDespesas',conta='Gestão Ambiental',rotulo='Total das Despesas Exceto Intra-Orçamentárias',coluna='DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)'),
 'rcl_12m':dict(anexo='RREO-Anexo 03',cod_conta='RREO3ReceitaCorrenteLiquida',coluna='TOTAL (ÚLTIMOS 12 MESES)')}

s=ses(); ent,_=getj(s,'/entes',{'limit':5000}); e=pd.DataFrame([x for x in ent.get('items',[]) if str(x.get('uf','')).upper()=='MG' and str(x.get('esfera','')).upper()=='M'])
e['cod_ibge_7']=e.cod_ibge.astype(str).str.zfill(7); e=e.sort_values('cod_ibge_7').drop_duplicates('cod_ibge_7'); assert len(e)==853
rows=e[['cod_ibge_7','ente','populacao']].rename(columns={'ente':'municipio','populacao':'populacao_siconfi'}).to_dict('records')

def one(row):
 code=row['cod_ibge_7']; s=ses(); attempts=[]; chosen=None; jchosen=None; fullitems=None; ufinal=None
 for demo in ['RREO','RREO Simplificado']:
  try:
   j,u=getj(s,'/rreo',{'an_exercicio':YEAR,'nr_periodo':6,'co_tipo_demonstrativo':demo,'id_ente':code,'limit':5000})
   items=j.get('items',[])
   if j.get('hasMore'):
    allitems=list(items); off=j.get('limit',5000)
    while True:
     j2,_=getj(s,'/rreo',{'an_exercicio':YEAR,'nr_periodo':6,'co_tipo_demonstrativo':demo,'id_ente':code,'limit':5000,'offset':off})
     allitems.extend(j2.get('items',[]))
     if not j2.get('hasMore'): break
     off+=j2.get('limit',5000)
    j['items']=allitems; items=allitems
   inst=sorted(set(str(x.get('instituicao','')).strip() for x in items if str(x.get('instituicao','')).strip()))
   pi=pref_items(items); pinst=sorted(set(str(x.get('instituicao','')).strip() for x in pi))
   attempts.append({'demonstrativo':demo,'itens_total':len(items),'instituicoes':inst,'itens_prefeitura':len(pi),'prefeituras':pinst,'url':u})
   if pi:
    chosen=demo; jchosen=j; fullitems=items; municipal=pi; ufinal=u; break
  except Exception as ex: attempts.append({'demonstrativo':demo,'erro':type(ex).__name__,'mensagem':str(ex)[:500]})
 rec={'cod_ibge_7':code,'municipio':row['municipio'],'populacao_siconfi':row['populacao_siconfi'],'ano_base':YEAR,'tentativas':attempts}
 if chosen is None:
  rec.update({'status_cobertura':'ND_SEM_DEMONSTRATIVO_MUNICIPAL_LOCALIZADO','demonstrativo':None,'instituicao_selecionada':None}); return rec
 # Preserve full official response incl. consortium as raw, plus selection metadata; transformation filters only Prefeitura.
 raw=RAW/f'rreo_{YEAR}_{code}_{chosen.replace(" ","_")}.json.gz'
 payload={'resposta_oficial':jchosen,'selecao_metodologica':{'regra':'Somente instituição Prefeitura Municipal representa o ente municipal neste painel; consórcios/associações associados ao mesmo cod_ibge não são somados.','instituicao_selecionada':sorted(set(str(x.get('instituicao','')).strip() for x in municipal)),'tentativas':attempts}}
 with gzip.open(raw,'wb',compresslevel=9) as f: f.write(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode())
 pinst=sorted(set(str(x.get('instituicao','')).strip() for x in municipal))
 rec.update({'status_cobertura':'OK','demonstrativo':chosen,'instituicao_selecionada':' | '.join(pinst),'instituicoes_total_resposta':len(set(str(x.get('instituicao','')).strip() for x in fullitems)),'itens_resposta_total':len(fullitems),'itens_prefeitura':len(municipal),'raw_file':raw.name,'raw_sha256':sha(raw),'raw_url_final':ufinal,'conflitos_metricas':''})
 conflicts=[]
 for name,sel in M.items():
  v,_=select(municipal,sel)
  if isinstance(v,dict): conflicts.append(name); rec[name]=None
  else: rec[name]=v
 rec['conflitos_metricas']=';'.join(conflicts); return rec

res=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
 for i,r in enumerate(ex.map(one,rows),1):
  res.append(r)
  if i%100==0: print('PROGRESS',i,'/853',flush=True)
df=pd.DataFrame(res).sort_values('cod_ibge_7')
# Remove verbose attempts from municipal normalized table; preserve separate audit.
pd.DataFrame([{'cod_ibge_7':r['cod_ibge_7'],'municipio':r['municipio'],'tentativas_json':json.dumps(r.get('tentativas',[]),ensure_ascii=False)} for r in res]).to_csv(AUD/'MG853_G5_L04_AUDITORIA_INSTITUICOES_RREO_2025_V0_2.csv',sep=';',index=False,encoding='utf-8-sig')
df2=df.drop(columns=['tentativas'])
# Derived indicators.
def rat(n,d):
 n=pd.to_numeric(n,errors='coerce'); d=pd.to_numeric(d,errors='coerce'); return (100*n/d).where(d>0)
for n in ['investimentos_liquidados','urbanismo_liquidado','habitacao_liquidado','saneamento_liquidado','gestao_ambiental_liquidado']:
 df2['pct_'+n+'_despesa']=rat(df2[n],df2['despesa_exceto_intra_liquidada'])
df2['pct_pessoal_orcamentario_rcl']=rat(df2['pessoal_encargos_liquidados'],df2['rcl_12m'])
pop=pd.to_numeric(df2.populacao_siconfi,errors='coerce')
df2['receita_exceto_intra_per_capita']=(pd.to_numeric(df2.receita_exceto_intra_realizada,errors='coerce')/pop).where(pop>0)
df2['despesa_exceto_intra_per_capita']=(pd.to_numeric(df2.despesa_exceto_intra_liquidada,errors='coerce')/pop).where(pop>0)
df2['fonte_id']='F-016'; df2['versao_transformacao']='G5-L04-NORM-2025-V0.2'; df2['status_registro']=df2.status_cobertura; df2['nivel_confianca']=df2.status_cobertura.map(lambda x:'ALTO_COM_RESSALVA_DECLARACAO_FISCAL' if x=='OK' else 'ND')
df2.to_csv(OUT/'MG853_G5_L04_BASE_MUNICIPAL_RREO_2025_V0_2.csv',sep=';',index=False,encoding='utf-8-sig',decimal=',')
# Tests
T=[]
def t(i,n,res,exp,ok,obs=''): T.append({'teste_id':i,'teste':n,'resultado':str(res),'esperado':str(exp),'aprovado':'SIM' if ok else 'NAO','observacao':obs})
ok=df2.status_cobertura.eq('OK').sum(); nd=853-ok
t('L04-25-T01','UNIVERSO_853',len(df2),853,len(df2)==853)
t('L04-25-T02','CHAVES_UNICAS',df2.cod_ibge_7.nunique(),853,df2.cod_ibge_7.nunique()==853)
t('L04-25-T03','COBERTURA_MUNICIPAL',f'OK={ok};ND={nd}','OK=853',ok==853)
t('L04-25-T04','INSTITUICAO_SELECIONADA_PREFEITURA',df2.instituicao_selecionada.fillna('').str.contains('Prefeitura Municipal',case=False).sum(),853,df2.instituicao_selecionada.fillna('').str.contains('Prefeitura Municipal',case=False).all())
t('L04-25-T05','SEM_CONFLITO_METRICA_APOS_FILTRO',df2.conflitos_metricas.fillna('').ne('').sum(),0,df2.conflitos_metricas.fillna('').eq('').all())
fallback=int(df2.demonstrativo.eq('RREO Simplificado').sum()); t('L04-25-T06','FALLBACK_SIMPLIFICADO_CONTROLADO',fallback,4,fallback==4,'Chácara, Monte Sião, Pequeri e Piranguinho')
multi=int((df2.instituicoes_total_resposta>1).sum()); t('L04-25-T07','RESPOSTAS_COM_MULTIPLAS_INSTITUICOES',multi,4,multi==4,'Barbacena, Itajubá, Leopoldina e Pouso Alegre; consórcios excluídos sem soma')
bounded=[c for c in df2.columns if c.startswith('pct_') and c!='pct_pessoal_orcamentario_rcl']; bad=0
for c in bounded:
 s=pd.to_numeric(df2[c],errors='coerce').dropna(); bad+=int(((s<0)|(s>100)).sum())
t('L04-25-T08','PERCENTUAIS_FUNCIONAIS_0_100',bad,0,bad==0)
neg=0
for c in M:
 s=pd.to_numeric(df2[c],errors='coerce').dropna(); neg+=int((s<0).sum())
t('L04-25-T09','METRICAS_NUCLEO_NAO_NEGATIVAS',neg,0,neg==0)
# semantic sample via re-extraction from exact preserved municipal items
samples=[]; div=0
for code in ['3106200','3170206','3118601','3131703','3100203','3164308','3152105','3162922','3133303','3168606','3140001','3109006','3105608','3132404','3138401','3152501','3115904','3143401','3149507','3151008']:
 r=df2[df2.cod_ibge_7.eq(code)].iloc[0]
 raw=RAW/r.raw_file
 with gzip.open(raw,'rb') as f: payload=json.loads(f.read().decode())
 municipal=pref_items(payload['resposta_oficial']['items'])
 for name,sel in M.items():
  exp,_=select(municipal,sel); got=r[name]
  same=(exp is None and pd.isna(got)) or (not isinstance(exp,dict) and exp is not None and pd.notna(got) and abs(float(exp)-float(got))<0.005)
  div+=0 if same else 1; samples.append({'cod_ibge_7':code,'municipio':r.municipio,'demonstrativo':r.demonstrativo,'instituicao':r.instituicao_selecionada,'indicador_id':name,'fonte':exp if not isinstance(exp,dict) else 'CONFLITO','normalizado':got,'confere':'SIM' if same else 'NAO'})
t('L04-25-T10','AMOSTRA_DIRIGIDA_REPRODUCAO',div,0,div==0,'20 municípios incluindo os 8 casos institucionais especiais')
pd.DataFrame(T).to_csv(AUD/'MG853_G5_L04_TESTES_RREO_2025_V0_2.csv',sep=';',index=False,encoding='utf-8-sig'); pd.DataFrame(samples).to_csv(AUD/'MG853_G5_L04_AMOSTRA_RREO_2025_V0_2.csv',sep=';',index=False,encoding='utf-8-sig')
summary={'lote':'G5-L04','fase':'2025_VALIDACAO_ESTADUAL_V0_2','ano':2025,'data_hora_utc':now(),'municipios':853,'cobertura_ok':int(ok),'cobertura_nd':int(nd),'fallback_rreo_simplificado':fallback,'respostas_multiplas_instituicoes':multi,'metricas_nucleo':len(M),'testes_total':len(T),'testes_aprovados':sum(x['aprovado']=='SIM' for x in T),'status':'APROVADO_PARA_EXPANSAO_SERIE_2023_2025' if all(x['aprovado']=='SIM' for x in T) else 'BLOQUEADO_PARA_REVISAO','regra_institucional':'Somente Prefeitura Municipal representa o ente municipal; consórcio/associação nunca é somado ao município.'}
(ROOT/'resumo_execucao.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(summary,ensure_ascii=False,indent=2))
if summary['status'].startswith('BLOQUEADO'): raise SystemExit('Falha em teste V0.2')
