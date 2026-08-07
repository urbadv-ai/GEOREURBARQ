from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

OUT=Path('mg853-g5-block1/probes/G5-L04_INSTITUICOES'); OUT.mkdir(parents=True,exist_ok=True)
BASE='https://apidatalake.tesouro.gov.br/ords/cdwhprd/siconfi/tt/rreo'
CODES=['3115904','3143401','3149507','3151008','3105608','3132404','3138401','3152501']
retry=Retry(total=5,connect=5,read=4,status=4,backoff_factor=1,status_forcelist=(429,500,502,503,504),allowed_methods=frozenset({'GET'}),raise_on_status=False)
s=requests.Session(); s.headers.update({'User-Agent':'MG853-G5-OABMG/3.0 (+auditoria oficial)'}); s.mount('https://',HTTPAdapter(max_retries=retry))
rows=[]
for code in CODES:
    for demo in ['RREO','RREO Simplificado']:
        try:
            r=s.get(BASE,params={'an_exercicio':2025,'nr_periodo':6,'co_tipo_demonstrativo':demo,'id_ente':code,'limit':5000},timeout=(20,120)); r.raise_for_status(); j=r.json()
            items=j.get('items',[])
            inst=sorted(set(str(x.get('instituicao','')).strip() for x in items if str(x.get('instituicao','')).strip()))
            prefs=[x for x in inst if 'prefeitura' in x.casefold()]
            rows.append({'cod_ibge_7':code,'demonstrativo':demo,'items':len(items),'instituicoes':inst,'prefeituras':prefs,'has_prefeitura':bool(prefs),'url_final':r.url})
        except Exception as e:
            rows.append({'cod_ibge_7':code,'demonstrativo':demo,'error':type(e).__name__,'message':str(e)[:500]})
res={'data_hora_utc':datetime.now(timezone.utc).replace(microsecond=0).isoformat(),'rows':rows,'regra_proposta':'Usar somente instituição municipal explicitamente identificada como Prefeitura Municipal; consórcio ou associação não representa o município. Se RREO padrão não contiver Prefeitura, testar RREO Simplificado. Se nenhum contiver, classificar ND_SEM_DEMONSTRATIVO_MUNICIPAL_LOCALIZADO.'}
(OUT/'probe_instituicoes_rreo_2025.json').write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(res,ensure_ascii=False,indent=2))
