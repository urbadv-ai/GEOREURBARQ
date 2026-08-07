from __future__ import annotations

import csv, hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

OUT=Path('mg853-g5-block2/output/G5-L06_CURRENT'); OUT.mkdir(parents=True,exist_ok=True)
URL='https://www.sgb.gov.br/pt/web/guest/minas-gerais-cartografia-de-suscetibilidade'
retry=Retry(total=6,connect=6,read=5,status=5,backoff_factor=1,status_forcelist=(429,500,502,503,504),allowed_methods=frozenset({'GET','HEAD'}),raise_on_status=False)
s=requests.Session(); s.headers.update({'User-Agent':'MG853-G5-OABMG/3.0 (+auditoria oficial)'}); s.mount('https://',HTTPAdapter(max_retries=retry))

def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()

def clean(t): return ' '.join(str(t or '').split())

r=s.get(URL,timeout=(20,180),allow_redirects=True); r.raise_for_status(); p=OUT/'pagina_sgb_mg.html'; p.write_bytes(r.content)
soup=BeautifulSoup(r.text,'lxml')
# Capture each link with multiple neighborhood contexts to allow robust later classification.
rows=[]
for a in soup.find_all('a',href=True):
 href=urljoin(r.url,a['href']); text=clean(a.get_text(' ',strip=True))
 parent=a.parent; parent_text=clean(parent.get_text(' ',strip=True)) if parent else ''
 # nearest previous heading/cell-like labels
 heading=a.find_previous(['h1','h2','h3','h4','h5','strong','b'])
 heading_text=clean(heading.get_text(' ',strip=True)) if heading else ''
 tr=a.find_parent('tr'); tr_text=clean(tr.get_text(' ',strip=True)) if tr else ''
 li=a.find_parent('li'); li_text=clean(li.get_text(' ',strip=True)) if li else ''
 rows.append({'link_text':text,'href':href,'heading_context':heading_text,'parent_context':parent_text[:800],'row_context':tr_text[:1200],'list_context':li_text[:800]})
with (OUT/'todos_links_contextualizados.csv').open('w',newline='',encoding='utf-8-sig') as f:
 w=csv.DictWriter(f,fieldnames=list(rows[0]) if rows else ['link_text','href','heading_context','parent_context','row_context','list_context']); w.writeheader(); w.writerows(rows)
# Candidate product links. No municipality-code attribution here.
prod=[]
for x in rows:
 hay=' '.join(x.values()).casefold()
 path=urlparse(x['href']).path.casefold()
 if any(k in hay for k in ['arquivo sig','sig','shapefile','geodatabase','mde','mapa','carta','suscetibilidade']) or path.endswith(('.zip','.rar','.7z','.shp','.gpkg','.gdb','.tif','.pdf')):
  if 'suscet' in hay or any(path.endswith(e) for e in ('.zip','.rar','.7z','.shp','.gpkg','.tif','.pdf')):
   prod.append(x)
# dedupe href
uniq={x['href']:x for x in prod}; prod=list(uniq.values())
with (OUT/'links_produtos_candidatos.csv').open('w',newline='',encoding='utf-8-sig') as f:
 w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(prod)
# DOM text blocks that appear to combine municipality + product links.
blocks=[]
for tag in soup.find_all(['tr','li','p','div']):
 links=tag.find_all('a',href=True)
 if not links: continue
 txt=clean(tag.get_text(' ',strip=True))
 if len(txt)<3 or len(txt)>1500: continue
 hrefs=[urljoin(r.url,a['href']) for a in links]
 if any('suscet' in (txt+' '+' '.join(hrefs)).casefold() or urlparse(h).path.casefold().endswith(('.zip','.rar','.7z','.pdf')) for h in hrefs):
  blocks.append({'text':txt,'hrefs':' | '.join(dict.fromkeys(hrefs)),'links':len(set(hrefs))})
# remove nested duplicate text/href combos
seen=set(); db=[]
for b in blocks:
 k=(b['text'],b['hrefs'])
 if k not in seen:seen.add(k);db.append(b)
with (OUT/'blocos_produto_publicados.csv').open('w',newline='',encoding='utf-8-sig') as f:
 w=csv.DictWriter(f,fieldnames=['text','hrefs','links']);w.writeheader();w.writerows(db)
# HEAD probe candidate links only; size/access metadata without downloads.
probe=[]
for x in prod:
 try:
  rr=s.head(x['href'],timeout=(10,30),allow_redirects=True)
  if rr.status_code in {405,403}:
   rr=s.get(x['href'],headers={'Range':'bytes=0-0'},stream=True,timeout=(10,30),allow_redirects=True)
  probe.append({'href':x['href'],'status':rr.status_code,'final_url':rr.url,'content_length':rr.headers.get('content-length',''),'content_type':rr.headers.get('content-type',''),'content_range':rr.headers.get('content-range','')})
 except Exception as e: probe.append({'href':x['href'],'status':'ERRO','error':type(e).__name__,'message':str(e)[:300]})
with (OUT/'probe_produtos.csv').open('w',newline='',encoding='utf-8-sig') as f:
 fields=sorted(set().union(*(x.keys() for x in probe))) if probe else ['href','status'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(probe)
summary={'lote':'G5-L06','fonte':'F-018','data_hora_utc':now(),'url':URL,'url_final':r.url,'sha256_pagina':sha(p),'links_total':len(rows),'produtos_candidatos':len(prod),'blocos_produto':len(db),'probes_ok':sum(str(x.get('status')).startswith('2') for x in probe),'status':'CATALOGO_ATUAL_PRESERVADO_PRONTO_PARA_EXTRACAO_DE_COBERTURA','regra':'Nenhum cod_ibge_7 atribuído por nome nesta etapa. Cobertura e código municipal serão derivados de metadados/pacote espacial ou validação geográfica oficial.'}
(OUT/'resumo_execucao.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
