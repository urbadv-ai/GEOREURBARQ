from __future__ import annotations
import asyncio, hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path
from playwright.async_api import async_playwright
OUT=Path('mg853-g5-block1/output/G5-L03_SELECTED_EDITIONS'); OUT.mkdir(parents=True,exist_ok=True)
PAGE='https://imrs.fjp.mg.gov.br/consultas/'
BASE='https://apiimrs.fjp.mg.gov.br/'
IDS=[90,97,116]
CODES=['AS_POPCADUNICO','AS_VULNERAEXTERNO','TR_EMPRSFTX']
def sha(b): return hashlib.sha256(b).hexdigest()
def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def years_recursive(x):
 out=set()
 def walk(v):
  if isinstance(v,dict):
   for k,val in v.items():
    if str(k).lower() in {'ano','year','edicao','edition'}:
     try:
      n=int(str(val)[:4]);
      if 1990<=n<=2030: out.add(n)
     except: pass
    walk(val)
  elif isinstance(v,list):
   for a in v: walk(a)
  elif isinstance(v,(int,float,str)):
   m=re.findall(r'\b(19\d{2}|20\d{2})\b',str(v))
   out.update(map(int,m))
 walk(x); return sorted(out)
async def fetch(page,url):
 return await page.evaluate("""async (url)=>{const r=await fetch(url,{headers:{Accept:'application/json'}});const t=await r.text();return {status:r.status,url:r.url,text:t}}""",url)
async def main():
 async with async_playwright() as p:
  b=await p.chromium.launch(headless=True,args=['--disable-dev-shm-usage']);ctx=await b.new_context(locale='pt-BR');page=await ctx.new_page();await page.goto(PAGE,wait_until='domcontentloaded',timeout=120000);await page.wait_for_timeout(2000)
  m=await fetch(page,BASE+'municipios/all-maps'); maps=json.loads(m['text']); gids=[int(x['gid']) for x in maps.get('municipios',[])]
  if len(gids)!=853: raise SystemExit(f'all-maps != 853: {len(gids)}')
  url=BASE+'municipios/editions?indicadores='+','.join(map(str,IDS))+'&municipios='+','.join(map(str,gids))
  e=await fetch(page,url); raw=e['text'].encode(); (OUT/'editions_selected_853.json').write_bytes(raw); obj=json.loads(e['text']); years=years_recursive(obj)
  meta={'data_hora_utc':now(),'indicator_ids':IDS,'codes':CODES,'municipios_gids':len(gids),'status':e['status'],'url':e['url'],'bytes':len(raw),'sha256':sha(raw),'years_detected':years,'response_type':type(obj).__name__,'top_keys':list(obj)[:20] if isinstance(obj,dict) else []}
  (OUT/'summary.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(meta,ensure_ascii=False,indent=2)); await b.close()
asyncio.run(main())
