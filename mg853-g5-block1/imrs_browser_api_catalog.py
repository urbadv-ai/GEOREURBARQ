from __future__ import annotations
import asyncio, csv, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
from playwright.async_api import async_playwright
OUT=Path('mg853-g5-block1/output/G5-L03_BROWSER_API_CATALOG'); OUT.mkdir(parents=True,exist_ok=True)
PAGE='https://imrs.fjp.mg.gov.br/consultas/'
BASE='https://apiimrs.fjp.mg.gov.br/'

def sha(b): return hashlib.sha256(b).hexdigest()
def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
async def fetch_json(page,ep,method='GET',body=None):
    return await page.evaluate("""async ({url,method,body}) => { const r=await fetch(url,{method,headers:{'Content-Type':'application/json','Accept':'application/json'},body:body?JSON.stringify(body):undefined}); const txt=await r.text(); return {status:r.status,url:r.url,text:txt}; }""",{'url':BASE+ep,'method':method,'body':body})
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(headless=True,args=['--disable-dev-shm-usage']); ctx=await b.new_context(locale='pt-BR'); page=await ctx.new_page(); await page.goto(PAGE,wait_until='domcontentloaded',timeout=120000); await page.wait_for_timeout(3000)
        manifest=[]; data={}
        for ep in ['indicadores/all','pesquisas/list-categories-indicators','municipios/all-maps','regionalizacao/municipios/']:
            x=await fetch_json(page,ep); raw=x['text'].encode(); fn=ep.replace('/','__')+'.json'; (OUT/fn).write_bytes(raw); manifest.append({'endpoint':ep,'status':x['status'],'bytes':len(raw),'sha256':sha(raw),'url':x['url'],'arquivo':fn}); data[ep]=json.loads(x['text'])
        inds=data['indicadores/all'].get('indicadores',[]); cats=data['pesquisas/list-categories-indicators']; rows=[]
        for dim in cats if isinstance(cats,list) else []:
            for sub in dim.get('subdimensoes') or []:
                for tema in sub.get('indicador_tema') or []:
                    ind=tema.get('indicadores') or {}
                    rows.append({'dimensao_id':dim.get('id'),'dimensao':dim.get('nome'),'subdimensao_id':sub.get('id'),'subdimensao':sub.get('nome'),'tema_id':tema.get('id'),'indicador_id':ind.get('id'),'codigo':ind.get('codigo'),'nome_curto':ind.get('nome_curto'),'nome_longo':ind.get('nome_longo'),'unidade':ind.get('unidade'),'fonte':ind.get('fonte'),'casas_decimais':ind.get('casas_decimais')})
        with open(OUT/'catalogo_hierarquico.csv','w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
        with open(OUT/'manifesto.csv','w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=list(manifest[0])); w.writeheader(); w.writerows(manifest)
        summary={'data_hora_utc':now(),'indicadores_all_count':len(inds),'catalogo_hierarquico_rows':len(rows),'municipios_all_maps':len(data['municipios/all-maps'].get('municipios',[])),'dimensoes':sorted({str(r['dimensao']) for r in rows})}
        (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(summary,ensure_ascii=False,indent=2)); await b.close()
asyncio.run(main())
