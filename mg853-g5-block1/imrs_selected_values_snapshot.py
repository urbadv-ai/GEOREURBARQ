from __future__ import annotations
import asyncio, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
from playwright.async_api import async_playwright
OUT=Path('mg853-g5-block1/output/G5-L03_SELECTED_VALUES_V2'); OUT.mkdir(parents=True,exist_ok=True)
PAGE='https://imrs.fjp.mg.gov.br/consultas/'
BASE='https://apiimrs.fjp.mg.gov.br/'
IDS=[90,97,116]; YEARS=['2023','2024']
def sha(b): return hashlib.sha256(b).hexdigest()
def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
async def req(page,url,method='GET',body=None):
 return await page.evaluate("""async ({url,method,body})=>{const r=await fetch(url,{method,headers:{Accept:'application/json','Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});const t=await r.text();return {status:r.status,url:r.url,text:t}}""",{'url':url,'method':method,'body':body})
async def main():
 async with async_playwright() as p:
  b=await p.chromium.launch(headless=True,args=['--disable-dev-shm-usage']);ctx=await b.new_context(locale='pt-BR');page=await ctx.new_page();await page.goto(PAGE,wait_until='domcontentloaded',timeout=120000);await page.wait_for_timeout(1500)
  calls=[]
  endpoints=[('municipios/all-maps','GET',None),('municipios/allValuesByCity','POST',{'years':YEARS,'indicators':IDS}),('municipios/vocabulario','POST',{'indicators':IDS}),('consultas/metadata?indicadores=AS_POPCADUNICO,AS_VULNERAEXTERNO,TR_EMPRSFTX','GET',None)]
  for ep,method,body in endpoints:
   x=await req(page,BASE+ep,method,body); raw=x['text'].encode(); fn=ep.replace('/','__').replace('?','__').replace('=','_').replace(',','_')+'.json'; (OUT/fn).write_bytes(raw)
   calls.append({'endpoint':ep,'method':method,'body':body,'status':x['status'],'url':x['url'],'bytes':len(raw),'sha256':sha(raw),'arquivo':fn})
  (OUT/'manifesto.json').write_text(json.dumps({'data_hora_utc':now(),'selected_ids':IDS,'years_requested':YEARS,'calls':calls},ensure_ascii=False,indent=2),encoding='utf-8')
  vals=json.loads((OUT/'municipios__allValuesByCity.json').read_text(encoding='utf-8'))
  def describe(x):
   if isinstance(x,dict):
    d={'type':'dict','keys':list(x)[:40]}
    if 'message' in x:
     m=x['message']; d['message_type']=type(m).__name__; d['message_len']=len(m) if hasattr(m,'__len__') else None; d['message_first']=m[0] if isinstance(m,list) and m else (list(m)[:10] if isinstance(m,dict) else str(m)[:500])
    return d
   if isinstance(x,list): return {'type':'list','len':len(x),'first_type':type(x[0]).__name__ if x else None,'first':x[0] if x else None}
   return {'type':type(x).__name__,'repr':repr(x)[:500]}
  summ={'values':describe(vals),'calls_status':{c['endpoint']:c['status'] for c in calls}}
  (OUT/'summary_structure.json').write_text(json.dumps(summ,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(summ,ensure_ascii=False,indent=2)); await b.close()
asyncio.run(main())
