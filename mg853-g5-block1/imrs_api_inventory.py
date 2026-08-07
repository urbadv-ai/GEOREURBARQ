from __future__ import annotations
import csv, hashlib, json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

OUT=Path('mg853-g5-block1/output/G5-L03_API_INVENTORY'); OUT.mkdir(parents=True,exist_ok=True)
BASE='https://apiimrs.fjp.mg.gov.br/'
ENDPOINTS=['indicadores/all','pesquisas/list-categories-indicators','municipios/all-maps','regionalizacao/municipios/']

def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def sha(b): return hashlib.sha256(b).hexdigest()
def safe(s): return re.sub(r'[^A-Za-z0-9_.-]+','_',s)
retry=Retry(total=6,connect=6,read=5,status=5,backoff_factor=1.5,status_forcelist=(429,500,502,503,504),allowed_methods=frozenset({'GET','POST'}),raise_on_status=False)
s=requests.Session(); s.headers.update({'User-Agent':'MG853-G5-OABMG/3.0 API audit','Accept':'application/json'}); s.mount('https://',HTTPAdapter(max_retries=retry))
manifest=[]; data={}
for ep in ENDPOINTS:
    r=s.get(BASE+ep,timeout=(15,180)); r.raise_for_status(); b=r.content
    fn=safe(ep)+'.json'; (OUT/fn).write_bytes(b); data[ep]=r.json()
    manifest.append({'endpoint':ep,'url_final':r.url,'status':r.status_code,'bytes':len(b),'sha256':sha(b),'content_type':r.headers.get('content-type',''),'arquivo':fn})

inds=data['indicadores/all'].get('indicadores',[])
# Flatten official category hierarchy as published by the platform.
cats=data['pesquisas/list-categories-indicators']
rows=[]
for dim in cats if isinstance(cats,list) else []:
    for sub in dim.get('subdimensoes') or []:
        for tema in sub.get('indicador_tema') or []:
            ind=tema.get('indicadores') or {}
            rows.append({
                'dimensao_id':dim.get('id'),'dimensao':dim.get('nome'),'subdimensao_id':sub.get('id'),'subdimensao':sub.get('nome'),
                'tema_id':tema.get('id'),'indicador_id':ind.get('id'),'codigo':ind.get('codigo'),'nome_curto':ind.get('nome_curto'),'nome_longo':ind.get('nome_longo'),
                'unidade':ind.get('unidade'),'fonte':ind.get('fonte'),'casas_decimais':ind.get('casas_decimais')
            })
with open(OUT/'catalogo_hierarquico_indicadores.csv','w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0].keys()) if rows else ['dimensao_id']); w.writeheader(); w.writerows(rows)
with open(OUT/'manifesto_api.csv','w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=list(manifest[0].keys())); w.writeheader(); w.writerows(manifest)
summary={'data_hora_utc':now(),'api_base':BASE,'endpoints':len(manifest),'indicadores_all_count':len(inds),'catalogo_hierarquico_rows':len(rows),'dimensoes':sorted({str(r.get('dimensao')) for r in rows}),'decision':'Inventario oficial para selecao semantica. Nao autoriza ingestao integral nem uso de indicadores redundantes.'}
(OUT/'resumo_api_inventory.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
if len(inds)<500 or len(rows)<500: sys.exit(2)
