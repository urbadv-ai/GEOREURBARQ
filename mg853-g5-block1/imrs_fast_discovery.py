from __future__ import annotations

import concurrent.futures
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

OUT=Path('mg853-g5-block1/output/G5-L03_FAST')
OUT.mkdir(parents=True,exist_ok=True)
BASE='https://imrs.fjp.mg.gov.br/'
PAGES=[BASE, urljoin(BASE,'consultas/'), urljoin(BASE,'sobre/'), urljoin(BASE,'repositorio/')]
retry=Retry(total=3,connect=3,read=2,status=2,backoff_factor=.8,status_forcelist=(429,500,502,503,504),allowed_methods=frozenset({'GET','HEAD'}),raise_on_status=False)
S=requests.Session(); S.headers.update({'User-Agent':'MG853-G5-OABMG/3.0 (+auditoria oficial)'})
S.mount('https://',HTTPAdapter(max_retries=retry,pool_connections=16,pool_maxsize=16))

def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def fetch(url,timeout=(8,18)):
    r=S.get(url,timeout=timeout,allow_redirects=True); r.raise_for_status(); return r

pages=[]; scripts=[]; links=[]; next_data=[]
for idx,url in enumerate(PAGES,1):
    try:
        r=fetch(url); txt=r.text
        (OUT/f'page_{idx:02d}.html').write_text(txt,encoding='utf-8')
        soup=BeautifulSoup(txt,'lxml')
        pages.append({'url':url,'final_url':r.url,'status':r.status_code,'bytes':len(r.content),'title':soup.title.get_text(strip=True) if soup.title else ''})
        for s in soup.find_all('script',src=True): scripts.append(urljoin(r.url,s['src']))
        for a in soup.find_all('a',href=True): links.append({'from':r.url,'text':' '.join(a.get_text(' ',strip=True).split()),'href':urljoin(r.url,a['href'])})
        nd=soup.find('script',id='__NEXT_DATA__')
        if nd and nd.string:
            try: next_data.append(json.loads(nd.string))
            except: pass
    except Exception as e:
        pages.append({'url':url,'error':type(e).__name__,'message':str(e)[:500]})

# Priorizar chunks que carregam app/consultas/main/webpack; limitar escopo para evitar gargalo.
scripts=list(dict.fromkeys(scripts))
priority=[]
for u in scripts:
    p=urlparse(u).path.lower()
    score=sum(k in p for k in ['consult','app','main','webpack','framework','page','chunk'])
    priority.append((score,u))
priority=[u for _,u in sorted(priority,key=lambda x:(-x[0],x[1]))[:24]]

patterns=[
    r'https?://[^"\'<>\s]+',
    r'(?<![A-Za-z0-9])/[A-Za-z0-9_./${}-]*(?:api|indicador|municip|consulta|export|download|csv|metad)[A-Za-z0-9_./?=&${}-]*',
    r'(?<![A-Za-z0-9])(?:api|indicador|municip|consulta|export|download|csv|metad)[A-Za-z0-9_./?=&${}-]{2,}',
]

def scan(u):
    try:
        r=fetch(u,(8,15)); txt=r.text
        hits=[]
        for pat in patterns:
            for m in re.finditer(pat,txt,re.I):
                h=m.group(0)[:600]
                if any(k in h.lower() for k in ['api','indic','municip','consulta','export','download','csv','metad','dimens','fonte']): hits.append(h)
        return {'url':u,'status':'OK','bytes':len(r.content),'hits':list(dict.fromkeys(hits))[:400]}
    except Exception as e:
        return {'url':u,'status':'ERRO','error':type(e).__name__,'message':str(e)[:500],'hits':[]}

with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
    scanned=list(ex.map(scan,priority))

all_hits=[]
for x in scanned:
    for h in x.get('hits',[]): all_hits.append({'script':x['url'],'hit':h})
# dedupe
seen=set(); dh=[]
for x in all_hits:
    k=x['hit']
    if k not in seen: seen.add(k); dh.append(x)

# Candidate downloadable links directly published in the pages.
candidates=[]
for x in links:
    text=(x['text']+' '+x['href']).lower()
    if any(k in text for k in ['csv','xlsx','download','dados','indicador','consulta','metodologia','dicionario','dicionário']): candidates.append(x)

result={
    'data_hora_utc':now(),
    'pages':pages,
    'scripts_total_discovered':len(scripts),
    'scripts_scanned':len(scanned),
    'scanned':scanned,
    'endpoint_hits':dh[:1500],
    'candidate_links':candidates[:500],
    'next_data':next_data,
    'decision':'Descoberta focalizada. Nenhum indicador será ingerido antes da matriz de contribuição marginal/redundância contra Censo, MUNIC, IDHM, IDSC e SINISA.'
}
(OUT/'imrs_fast_discovery.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
# compact text shortlist
short=[]
for x in dh:
    h=x['hit']
    if any(k in h.lower() for k in ['/api','csv','export','download','indicador','municip']): short.append(h)
(OUT/'endpoint_shortlist.txt').write_text('\n'.join(list(dict.fromkeys(short))[:300]),encoding='utf-8')
print(json.dumps({'status':'OK','pages_ok':sum('status' in p and p['status']==200 for p in pages),'scripts_discovered':len(scripts),'scripts_scanned':len(scanned),'endpoint_hits':len(dh),'candidate_links':len(candidates),'time':now()},ensure_ascii=False,indent=2))
