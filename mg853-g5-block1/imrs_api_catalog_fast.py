import json, csv, hashlib, sys
from datetime import datetime, timezone
from pathlib import Path
import requests
OUT=Path('mg853-g5-block1/output/G5-L03_API_CATALOG_FAST'); OUT.mkdir(parents=True,exist_ok=True)
BASE='https://apiimrs.fjp.mg.gov.br/'
s=requests.Session(); s.headers.update({'User-Agent':'Mozilla/5.0 MG853-G5-OABMG','Accept':'application/json'})
raw={}; manifest=[]
for ep in ['indicadores/all','pesquisas/list-categories-indicators']:
 r=s.get(BASE+ep,timeout=(10,120)); r.raise_for_status(); b=r.content; raw[ep]=r.json(); fn=ep.replace('/','__')+'.json'; (OUT/fn).write_bytes(b); manifest.append({'endpoint':ep,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'status':r.status_code,'url':r.url})
inds=raw['indicadores/all'].get('indicadores',[]); cats=raw['pesquisas/list-categories-indicators']; rows=[]
for dim in cats if isinstance(cats,list) else []:
 for sub in dim.get('subdimensoes') or []:
  for tema in sub.get('indicador_tema') or []:
   ind=tema.get('indicadores') or {}
   rows.append({'dimensao':dim.get('nome'),'subdimensao':sub.get('nome'),'indicador_id':ind.get('id'),'codigo':ind.get('codigo'),'nome_curto':ind.get('nome_curto'),'nome_longo':ind.get('nome_longo'),'unidade':ind.get('unidade'),'fonte':ind.get('fonte'),'casas_decimais':ind.get('casas_decimais')})
with open(OUT/'catalogo.csv','w',newline='',encoding='utf-8-sig') as f:
 w=csv.DictWriter(f,fieldnames=list(rows[0]) if rows else ['dimensao']); w.writeheader(); w.writerows(rows)
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
summary={'indicadores_all':len(inds),'catalogo_rows':len(rows),'dimensoes':sorted({str(r['dimensao']) for r in rows})}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False))
if len(inds)<500 or len(rows)<500: sys.exit(2)
