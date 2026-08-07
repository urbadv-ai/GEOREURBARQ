from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOT=os.environ.get('LOT_ID','').strip().upper()
ROOT=Path('mg853-g5-block2/output')/LOT
ROOT.mkdir(parents=True,exist_ok=True)
retry=Retry(total=6,connect=6,read=5,status=5,backoff_factor=1.5,status_forcelist=(429,500,502,503,504),allowed_methods=frozenset({'GET','HEAD'}),raise_on_status=False)
S=requests.Session(); S.headers.update({'User-Agent':'MG853-G5-OABMG/3.0 (+auditoria oficial)'})
S.mount('https://',HTTPAdapter(max_retries=retry,pool_connections=8,pool_maxsize=8))

def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def get(url,name):
 p=ROOT/name
 r=S.get(url,timeout=(20,180),allow_redirects=True); r.raise_for_status(); p.write_bytes(r.content)
 return p,r.url,r.headers.get('content-type','')
def write_csv(name,rows,fields):
 with (ROOT/name).open('w',newline='',encoding='utf-8-sig') as f:
  w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)


def l06():
 pages=[
  'https://www.sgb.gov.br/produtos-por-estado-cartografia-de-suscetibilidade',
  'https://www.sgb.gov.br/suscetibilidade-mg'
 ]
 links=[]; pageinfo=[]
 for i,u in enumerate(pages,1):
  try:
   p,final,ctype=get(u,f'pagina_{i:02d}.html')
   soup=BeautifulSoup(p.read_text(encoding='utf-8',errors='replace'),'lxml')
   pageinfo.append({'url':u,'final_url':final,'sha256':sha(p),'bytes':p.stat().st_size,'title':soup.title.get_text(' ',strip=True) if soup.title else ''})
   for a in soup.find_all('a',href=True):
    href=urljoin(final,a['href']); text=' '.join(a.get_text(' ',strip=True).split())
    if any(k in (text+' '+href).lower() for k in ['mg','minas','suscet','carta','sig','shp','zip','tif','mde','geodatabase']):
     links.append({'text':text,'href':href,'source_page':final})
  except Exception as e:
   pageinfo.append({'url':u,'error':type(e).__name__,'message':str(e)[:500]})
 # dedupe
 seen=set(); ded=[]
 for x in links:
  if x['href'] not in seen: seen.add(x['href']); ded.append(x)
 write_csv('inventario_links_sgb_mg.csv',ded,['text','href','source_page'])
 # Heurística apenas de catálogo: extrair nomes municipais dos textos, sem classificar cobertura ainda.
 municipal_candidates=[]
 for x in ded:
  txt=x['text'].strip()
  if txt and len(txt)<120 and re.search(r'(?i)mg|minas|suscetibilidade|carta',txt): municipal_candidates.append(txt)
 result={'lote':'G5-L06','fonte':'F-018','data_hora_utc':now(),'pages':pageinfo,'links_total':len(ded),'municipal_text_candidates':municipal_candidates[:300],'status':'CATALOGO_E_COBERTURA_EM_VALIDACAO','regra':'Somente produto municipal explicitamente publicado será classificado MAPEADO. Ausência de link ou catálogo nunca será baixo risco.'}
 (ROOT/'resumo_l06.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'status':result['status'],'links':len(ded),'pages_ok':sum('sha256' in x for x in pageinfo)},ensure_ascii=False,indent=2))


def local(tag): return tag.split('}',1)[-1]
def l07():
 services={
  'wfs':'https://geoserver.meioambiente.mg.gov.br/ows?service=WFS&request=GetCapabilities&version=2.0.0',
  'wms':'https://geoserver.meioambiente.mg.gov.br/ows?service=WMS&request=GetCapabilities&version=1.3.0',
  'wcs':'https://geoserver.meioambiente.mg.gov.br/ows?service=WCS&request=GetCapabilities&version=2.0.1',
  'csw':'https://idesisema.meioambiente.mg.gov.br/geonetwork/srv/por/csw?service=CSW&version=2.0.2&request=GetCapabilities'
 }
 info={}; layers=[]
 for key,u in services.items():
  try:
   p,final,ctype=get(u,f'{key}_getcapabilities.xml')
   info[key]={'url':u,'final_url':final,'sha256':sha(p),'bytes':p.stat().st_size,'content_type':ctype}
   if key in {'wfs','wms'}:
    root=ET.fromstring(p.read_bytes())
    # WFS FeatureType / WMS Layer containing Name and Title
    for elem in root.iter():
     if local(elem.tag) not in {'FeatureType','Layer'}: continue
     name=title=''
     for ch in list(elem):
      if local(ch.tag)=='Name' and ch.text: name=ch.text.strip()
      elif local(ch.tag)=='Title' and ch.text: title=ch.text.strip()
     if name: layers.append({'service':key,'name':name,'title':title})
  except Exception as e: info[key]={'url':u,'error':type(e).__name__,'message':str(e)[:500]}
 # dedupe layer-service
 ded={ (x['service'],x['name']):x for x in layers }
 layers=list(ded.values())
 groups={
  'UC_AREAS_PROTEGIDAS':['unidade de conserva','uc ','protegida','reserva','rppn','apa ','parque','zona de amortecimento'],
  'HIDROGRAFIA_RECURSOS_HIDRICOS':['hidrograf','curso d','drenagem','rio ','bacia','subbacia','nascente','reservatorio','reservatório','massa d','aquífer','aquifer'],
  'RESTRICOES_CONDICIONANTES':['restri','condicion','app','preservacao permanente','preservação permanente','zoneamento','vulnerabilidade natural','karst','caverna'],
  'AREAS_CONTAMINADAS_PASSIVOS':['contamin','passivo','reabilita','solo contamin','area suspeita','área suspeita'],
  'USO_COBERTURA':['uso e cobertura','uso do solo','cobertura da terra','mapbiomas','vegetacao','vegetação','formacao florestal']
 }
 candidates=[]
 for x in layers:
  txt=(x['name']+' '+x['title']).casefold()
  for g,keys in groups.items():
   if any(k.casefold() in txt for k in keys): candidates.append({**x,'grupo_candidato':g}); break
 write_csv('inventario_camadas_wfs_wms.csv',layers,['service','name','title'])
 write_csv('camadas_candidatas_5_grupos.csv',candidates,['service','name','title','grupo_candidato'])
 result={'lote':'G5-L07','fonte':'F-006','data_hora_utc':now(),'services':info,'layers_total':len(layers),'candidates_total':len(candidates),'candidates_by_group':{},'status':'CAPABILITIES_E_CANDIDATAS_INVENTARIADAS','regra':'Heurística apenas pré-seleciona; cada camada precisa metadado, cobertura, data, CRS, licença e não redundância antes do sub-snapshot.'}
 for g in groups: result['candidates_by_group'][g]=sum(x['grupo_candidato']==g for x in candidates)
 (ROOT/'resumo_l07.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'status':result['status'],'services_ok':sum('sha256' in x for x in info.values()),'layers_total':len(layers),'candidates_total':len(candidates),'groups':result['candidates_by_group']},ensure_ascii=False,indent=2))

if LOT=='G5-L06': l06()
elif LOT=='G5-L07': l07()
else: raise SystemExit('LOT_ID inválido')
