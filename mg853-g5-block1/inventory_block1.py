from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOT = os.environ.get('LOT_ID', '').strip().upper()
OUT = Path('mg853-g5-block1/output') / LOT
OUT.mkdir(parents=True, exist_ok=True)

retry = Retry(total=6, connect=6, read=5, status=5, backoff_factor=1.5,
              status_forcelist=(429,500,502,503,504),
              allowed_methods=frozenset({'GET','HEAD'}), raise_on_status=False)
S = requests.Session()
S.headers.update({'User-Agent':'MG853-G5-OABMG/3.0 (+auditoria oficial; contato institucional)'})
S.mount('https://', HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8))
TIMEOUT=(20,180)

records=[]
errors=[]

def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def sha256(path: Path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()

def slug(s:str)->str:
    s=unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+','_',s).strip('_')

def save_bytes(url:str, name:str, required=True):
    p=OUT/name
    try:
        with S.get(url,stream=True,timeout=TIMEOUT,allow_redirects=True) as r:
            r.raise_for_status(); total=0
            with p.open('wb') as f:
                for chunk in r.iter_content(1024*1024):
                    if chunk: f.write(chunk); total+=len(chunk)
        rec={'url':url,'final_url':r.url,'file':name,'bytes':total,'sha256':sha256(p),'status':'OK','time':now()}
        records.append(rec); return p
    except Exception as e:
        errors.append({'url':url,'file':name,'error':type(e).__name__,'message':str(e)[:1000],'time':now()})
        if required: raise
        return None

def save_text(url:str,name:str,required=True):
    p=save_bytes(url,name,required)
    return p

def read_table_auto(path:Path, nrows=None):
    ext=path.suffix.lower()
    if ext in ('.xlsx','.xls'):
        return pd.read_excel(path,nrows=nrows)
    raw=path.read_bytes()[:200000]
    enc='utf-8-sig'
    for cand in ['utf-8-sig','utf-8','latin-1']:
        try: raw.decode(cand); enc=cand; break
        except: pass
    sample=raw.decode(enc,errors='replace')
    sep=';'
    try: sep=csv.Sniffer().sniff(sample[:10000],delimiters=';,\t|').delimiter
    except: pass
    return pd.read_csv(path,sep=sep,encoding=enc,nrows=nrows,low_memory=False)

def inventory_df(df:pd.DataFrame, source:str):
    return {'source':source,'rows':int(len(df)),'columns':list(map(str,df.columns)),
            'dtypes':{str(c):str(df[c].dtype) for c in df.columns},
            'nulls':{str(c):int(df[c].isna().sum()) for c in df.columns}}

def inspect_zip(path:Path):
    out=[]
    with zipfile.ZipFile(path) as z:
        for i in z.infolist(): out.append({'name':i.filename,'bytes':i.file_size,'compressed':i.compress_size})
    return out

def write_json(name,obj): (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')


def l03():
    pages={
      'plataforma':'https://imrs.fjp.mg.gov.br/',
      'consultas':'https://imrs.fjp.mg.gov.br/consultas/',
      'sobre':'https://imrs.fjp.mg.gov.br/sobre/',
      'repositorio':'https://imrs.fjp.mg.gov.br/repositorio/',
    }
    all_scripts=[]; all_links=[]
    for key,url in pages.items():
        p=save_bytes(url,f'{key}.html',required=False)
        if not p: continue
        html=p.read_text(encoding='utf-8',errors='replace')
        soup=BeautifulSoup(html,'lxml')
        for s in soup.find_all('script',src=True): all_scripts.append(urljoin(url,s['src']))
        for a in soup.find_all('a',href=True):
            all_links.append({'page':key,'text':' '.join(a.get_text(' ',strip=True).split()),'href':urljoin(url,a['href'])})
    all_scripts=list(dict.fromkeys(all_scripts))
    endpoint_hits=[]
    patterns=[r'https?://[^"\'\s]+',r'/api/[A-Za-z0-9_./?=&${}-]+',r'api/[A-Za-z0-9_./?=&${}-]+',r'export[A-Za-z0-9_./?=&${}-]*',r'download[A-Za-z0-9_./?=&${}-]*']
    for idx,u in enumerate(all_scripts[:40],1):
        try:
            r=S.get(u,timeout=(20,90)); r.raise_for_status(); txt=r.text
            (OUT/f'js_{idx:02d}.txt').write_text(txt,encoding='utf-8',errors='replace')
            for pat in patterns:
                for m in re.finditer(pat,txt,re.I):
                    v=m.group(0)
                    if any(k in v.lower() for k in ['api','indic','municip','consulta','csv','export','download','metad']):
                        endpoint_hits.append({'script':u,'hit':v[:500]})
        except Exception as e:
            errors.append({'url':u,'file':'js','error':type(e).__name__,'message':str(e)[:500],'time':now()})
    # dedupe
    seen=set(); ded=[]
    for x in endpoint_hits:
        k=(x['script'],x['hit'])
        if k not in seen: seen.add(k); ded.append(x)
    write_json('inventory_l03.json',{'scripts':all_scripts,'links':all_links,'endpoint_hits':ded[:2000],
                                      'decision':'Nao baixar 700 indicadores indiscriminadamente; selecionar por contribuicao marginal antes do subsnapshot.'})


def l04():
    base='https://apidatalake.tesouro.gov.br/ords/cdwhprd/siconfi/tt'
    # API documentation snapshot
    save_bytes('https://apidatalake.tesouro.gov.br/docs/siconfi.yaml','siconfi_openapi.yaml',required=False)
    # entes MG
    params={'co_esfera':'M','co_uf':'31','limit':5000}
    r=S.get(base+'/entes',params=params,timeout=TIMEOUT); r.raise_for_status(); j=r.json()
    items=j.get('items',[])
    write_json('entes_mg_raw.json',j)
    pd.DataFrame(items).to_csv(OUT/'entes_mg.csv',index=False,encoding='utf-8-sig')
    # sample BH current closed exercise 2025
    sample='3106200'; year=2025
    r=S.get(base+'/dca',params={'an_exercicio':year,'id_ente':sample,'limit':5000},timeout=TIMEOUT); r.raise_for_status(); jd=r.json()
    write_json('dca_bh_2025_raw.json',jd)
    d=pd.DataFrame(jd.get('items',[]))
    if not d.empty: d.to_csv(OUT/'dca_bh_2025.csv',index=False,encoding='utf-8-sig')
    # RREO final period for sample, try both with and without filters
    candidates=[]
    for p in [
      {'an_exercicio':2025,'nr_periodo':6,'co_tipo_demonstrativo':'RREO','id_ente':sample,'limit':5000},
      {'an_exercicio':2025,'nr_periodo':6,'id_ente':sample,'limit':5000},
    ]:
        try:
            rr=S.get(base+'/rreo',params=p,timeout=TIMEOUT); rr.raise_for_status(); jr=rr.json(); candidates.extend(jr.get('items',[]))
            write_json('rreo_bh_2025_raw.json',jr)
            if candidates: break
        except Exception as e: errors.append({'url':base+'/rreo','file':'rreo','error':type(e).__name__,'message':str(e),'time':now()})
    rd=pd.DataFrame(candidates)
    if not rd.empty: rd.to_csv(OUT/'rreo_bh_2025.csv',index=False,encoding='utf-8-sig')
    # inventory + account matches
    inv={'entes_count':len(items),'entes_cols':list(pd.DataFrame(items).columns),'dca':inventory_df(d,'DCA') if not d.empty else {},
         'rreo':inventory_df(rd,'RREO') if not rd.empty else {}}
    matches=[]
    for label,df in [('DCA',d),('RREO',rd)]:
        if df.empty: continue
        textcols=[c for c in df.columns if df[c].dtype=='object']
        for _,row in df.iterrows():
            text=' | '.join(str(row[c]) for c in textcols if pd.notna(row[c]))
            if re.search(r'urban|habit|sane|ambient|invest|receita corrente l[ií]quida|pessoal|d[ií]vida',text,re.I):
                matches.append({'dataset':label,**{str(c):row[c] for c in df.columns if c in textcols or str(c).startswith('vl_')}})
                if len(matches)>=500: break
    write_json('inventory_l04.json',{'inventory':inv,'semantic_account_matches':matches})


def l05():
    csv_url='https://atlasdigital.mdr.gov.br/arquivos/BD_Atlas_1991_2025_v1.0_2026.04.23_Consolidado.csv'
    p=save_bytes(csv_url,'atlas_1991_2025.csv')
    df=read_table_auto(p)
    inv=inventory_df(df,'Atlas CSV 1991-2025')
    # detect MG field
    mgmask=pd.Series(False,index=df.index)
    candidates=[]
    for c in df.columns:
        s=df[c].astype(str).str.strip()
        cnt=int((s.str.upper()=='MG').sum())
        if cnt: candidates.append({'column':str(c),'mg_count':cnt}); mgmask |= s.str.upper().eq('MG')
    mg=df.loc[mgmask].copy() if mgmask.any() else pd.DataFrame()
    if not mg.empty: mg.to_csv(OUT/'atlas_mg_raw.csv',index=False,encoding='utf-8-sig')
    write_json('inventory_l05.json',{'inventory':inv,'mg_detection':candidates,'mg_rows':len(mg),
                                     'sample':mg.head(5).fillna('').astype(str).to_dict(orient='records') if not mg.empty else []})


def l09():
    page='https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/habitacao/programa-minha-casa-minha-vida/bases-de-dados-do-programa-minha-casa-minha-vida'
    htmlp=save_bytes(page,'pagina_mcmv.html')
    html=htmlp.read_text(encoding='utf-8',errors='replace')
    soup=BeautifulSoup(html,'lxml')
    links=[]
    for a in soup.find_all('a',href=True):
        text=' '.join(a.get_text(' ',strip=True).split())
        href=urljoin(page,a['href'])
        if re.search(r'MCMV|FGTS|SNHIS|Regularidade|Dicion',text,re.I): links.append({'text':text,'href':href})
    write_json('links_mcmv_snhis.json',links)
    known={
      'mcmv_subsidiado.zip':'https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/habitacao/programa-minha-casa-minha-vida/arquivos/mcmv_subsidiado_202606302.zip',
      'mcmv_fgts_sintetico.zip':'https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/habitacao/programa-minha-casa-minha-vida/arquivos/mcmv_financ_sintetico_20260724.zip',
      'dicionario.pdf':'https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/habitacao/arquivos-1/Dicionarios_SNH_2025_10_09.pdf',
    }
    zinv={}; data_inv=[]
    for name,url in known.items():
        p=save_bytes(url,name,required=False)
        if p and p.suffix.lower()=='.zip':
            zinv[name]=inspect_zip(p)
            with zipfile.ZipFile(p) as z:
                for info in z.infolist():
                    if info.is_dir(): continue
                    ext=Path(info.filename).suffix.lower()
                    if ext not in ('.csv','.txt','.xlsx','.xls'): continue
                    target=OUT/('unz_'+slug(Path(info.filename).stem)+ext)
                    target.write_bytes(z.read(info.filename))
                    try:
                        df=read_table_auto(target)
                        data_inv.append(inventory_df(df,info.filename))
                        # filter MG if UF column found
                        mgmask=pd.Series(False,index=df.index)
                        for c in df.columns:
                            s=df[c].astype(str).str.strip().str.upper()
                            if (s=='MG').sum(): mgmask |= s.eq('MG')
                        if mgmask.any(): df.loc[mgmask].to_csv(OUT/(target.stem+'_MG.csv'),index=False,encoding='utf-8-sig')
                    except Exception as e: errors.append({'url':url,'file':info.filename,'error':type(e).__name__,'message':str(e)[:500],'time':now()})
    # discover SNHIS downloadable href(s) from page
    snhis=[]
    for x in links:
        if re.search(r'regularidade.*SNHIS|SNHIS',x['text'],re.I) and not re.search(r'dicion',x['text'],re.I):
            snhis.append(x)
            if len(snhis)<=5:
                u=x['href']
                # handle Plone /view links by requesting; if html, search @@download
                try:
                    r=S.get(u,timeout=TIMEOUT,allow_redirects=True); r.raise_for_status()
                    ctype=r.headers.get('content-type','')
                    suffix=Path(urlparse(r.url).path).suffix or '.bin'
                    if 'text/html' not in ctype:
                        p=OUT/f'snhis_{len(snhis)}{suffix}'; p.write_bytes(r.content); records.append({'url':u,'final_url':r.url,'file':p.name,'bytes':len(r.content),'sha256':sha256(p),'status':'OK','time':now()})
                except Exception as e: errors.append({'url':u,'file':'SNHIS','error':type(e).__name__,'message':str(e)[:500],'time':now()})
    write_json('inventory_l09.json',{'zip_inventory':zinv,'data_inventory':data_inv,'snhis_links':snhis})

funcs={'G5-L03':l03,'G5-L04':l04,'G5-L05':l05,'G5-L09':l09}
if LOT not in funcs: raise SystemExit(f'LOT_ID inválido: {LOT}')
status='OK'
try: funcs[LOT]()
except Exception as e:
    status='ERRO_CONTROLADO'; errors.append({'url':'','file':LOT,'error':type(e).__name__,'message':str(e)[:2000],'time':now()})
write_json('manifest.json',records)
write_json('errors.json',errors)
write_json('summary.json',{'lot':LOT,'status':status,'files':len(records),'errors':len(errors),'time':now()})
print(json.dumps(json.loads((OUT/'summary.json').read_text()),ensure_ascii=False,indent=2))
