from __future__ import annotations

import asyncio, hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

OUT=Path('mg853-g5-block1/output/G5-L03_BROWSER')
OUT.mkdir(parents=True,exist_ok=True)
URL='https://imrs.fjp.mg.gov.br/consultas/'

def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def safe(s): return re.sub(r'[^A-Za-z0-9_.-]+','_',s)[:140]
def sha(b): return hashlib.sha256(b).hexdigest()

async def main():
    records=[]; bodies=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,args=['--disable-dev-shm-usage'])
        context=await browser.new_context(locale='pt-BR',user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142.0 Safari/537.36')
        page=await context.new_page()
        async def on_response(resp):
            try:
                req=resp.request
                rt=req.resource_type
                u=resp.url
                ct=(resp.headers.get('content-type') or '').lower()
                rec={'url':u,'status':resp.status,'resource_type':rt,'method':req.method,'content_type':ct}
                if rt in ('xhr','fetch') or any(k in u.lower() for k in ['api','indic','municip','consult','csv','export','download']):
                    try:
                        b=await resp.body()
                        rec['bytes']=len(b); rec['sha256']=sha(b)
                        if len(b)<=5_000_000:
                            ext='.json' if 'json' in ct else ('.csv' if 'csv' in ct else '.txt')
                            fn=f"resp_{len(bodies):03d}_{safe(urlparse(u).path)}{ext}"
                            (OUT/fn).write_bytes(b); bodies.append(fn); rec['saved_as']=fn
                    except Exception as e: rec['body_error']=repr(e)
                records.append(rec)
            except Exception:
                pass
        page.on('response',on_response)
        nav_error=None
        try:
            await page.goto(URL,wait_until='domcontentloaded',timeout=120000)
            await page.wait_for_timeout(25000)
        except Exception as e:
            nav_error=repr(e)
        html=await page.content(); (OUT/'consultas_rendered.html').write_text(html,encoding='utf-8')
        text=(await page.locator('body').inner_text())[:100000]; (OUT/'body_text.txt').write_text(text,encoding='utf-8')
        controls=await page.locator('input,select,button,[role="button"]').evaluate_all("els => els.map((e,i)=>({i,tag:e.tagName,type:e.type||'',name:e.name||'',id:e.id||'',placeholder:e.placeholder||'',text:(e.innerText||e.value||'').trim().slice(0,200),aria:e.getAttribute('aria-label')||'',cls:e.className||''}))")
        (OUT/'controls.json').write_text(json.dumps(controls,ensure_ascii=False,indent=2),encoding='utf-8')
        # Try interacting only with the municipality-search control if it exists; no submission of analytical query.
        inputs=page.locator('input')
        for i in range(await inputs.count()):
            el=inputs.nth(i)
            ph=(await el.get_attribute('placeholder') or '').lower()
            if 'buscar' in ph:
                try:
                    await el.fill('Belo Horizonte')
                    await page.wait_for_timeout(3000)
                    await el.fill('')
                    await page.wait_for_timeout(2000)
                except Exception: pass
                break
        scripts=await page.locator('script[src]').evaluate_all("els => els.map(e=>e.src)")
        result={'data_hora_utc':now(),'url':URL,'final_url':page.url,'title':await page.title(),'nav_error':nav_error,'responses_total':len(records),'network_records':records,'saved_bodies':bodies,'controls':controls,'scripts':scripts,'body_excerpt':text[:5000]}
        (OUT/'imrs_browser_discovery.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        await page.screenshot(path=str(OUT/'consultas.png'),full_page=True)
        await browser.close()
    interesting=[r for r in records if r.get('resource_type') in ('xhr','fetch') or any(k in r.get('url','').lower() for k in ['api','indic','municip','csv','export','download'])]
    print(json.dumps({'status':'OK' if not nav_error else 'COM_RESSALVA','final_url':result['final_url'],'title':result['title'],'network_total':len(records),'interesting':len(interesting),'saved_bodies':len(bodies),'nav_error':nav_error},ensure_ascii=False,indent=2))

asyncio.run(main())
