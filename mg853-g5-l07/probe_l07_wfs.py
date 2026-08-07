import csv, hashlib, json, os, re, sys, time
from pathlib import Path
import requests
from xml.etree import ElementTree as ET

BASE='https://geoserver.meioambiente.mg.gov.br/ows'
OUT=Path('out_l07_probe')
OUT.mkdir(exist_ok=True)
LAYERS=[
('L07-G1-UC','UC_AREAS_PROTEGIDAS','IDE:ide_2010_mg_unidades_conservacao_municipais_pol'),
('L07-G1-UC','UC_AREAS_PROTEGIDAS','IDE:ide_2010_mg_unidades_conservacao_estaduais_pol'),
('L07-G1-UC','UC_AREAS_PROTEGIDAS','IDE:ide_2010_mg_unidades_conservacao_federais_pol'),
('L07-G2-CH','HIDROGRAFIA_RECURSOS_HIDRICOS','IDE:ide_1108_mg_circunscricoes_hidrograficas_pol'),
('L07-G3-RH-REST','RESTRICOES_CONDICIONANTES','IDE:ide_2007_mg_restricao_contole_rh_sub_pol'),
('L07-G4-ACR','AREAS_CONTAMINADAS_PASSIVOS','IDE:ide_1902_mg_areas_contaminadas_reabilitadas_pto'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area1_pol'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area2_pol'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area3_pol'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area4_pol'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area5_pol'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area6_pol'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area7_pol'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area8_pol'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area9_pol'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area10_pol'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area11_pol'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area12_pol'),
('L07-G5-USO','USO_COBERTURA','IDE:ide_210603_mg_uso_cobertura_mapcar_area13_pol'),
]

def sha256_bytes(b): return hashlib.sha256(b).hexdigest()
def safe(s): return re.sub(r'[^A-Za-z0-9_.-]+','_',s)

def get(session, params, timeout=120):
    last=None
    for i in range(4):
        try:
            r=session.get(BASE, params=params, timeout=timeout, allow_redirects=True)
            r.raise_for_status(); return r
        except Exception as e:
            last=e; time.sleep(2*(i+1))
    raise last

def parse_schema(xml_bytes):
    root=ET.fromstring(xml_bytes)
    fields=[]
    for el in root.iter():
        tag=el.tag.split('}')[-1]
        if tag=='element' and el.attrib.get('name') and el.attrib.get('type'):
            fields.append((el.attrib.get('name'),el.attrib.get('type'),el.attrib.get('minOccurs',''),el.attrib.get('maxOccurs','')))
    return fields

def parse_hits(xml_bytes):
    root=ET.fromstring(xml_bytes)
    for k in ('numberMatched','numberOfFeatures'):
        if k in root.attrib:
            return root.attrib[k]
    return ''

s=requests.Session(); s.headers.update({'User-Agent':'MG853-G5-L07/1.0 OABMG research snapshot'})
rows=[]; manifest=[]
for logical_id,group,layer in LAYERS:
    stem=safe(layer.replace(':','__'))
    row={'logical_id':logical_id,'grupo':group,'layer_name':layer}
    try:
        r=get(s,{'service':'WFS','version':'2.0.0','request':'DescribeFeatureType','typeNames':layer})
        p=OUT/f'{stem}__DescribeFeatureType.xml'; p.write_bytes(r.content)
        fields=parse_schema(r.content)
        row.update({'describe_http':r.status_code,'describe_bytes':len(r.content),'describe_sha256':sha256_bytes(r.content),'schema_field_count':len(fields),'schema_fields':' | '.join([f'{a}:{b}' for a,b,_,__ in fields])})
        manifest.append([p.name,len(r.content),sha256_bytes(r.content),r.url])
    except Exception as e:
        row['describe_error']=repr(e); fields=[]
    try:
        r=get(s,{'service':'WFS','version':'2.0.0','request':'GetFeature','typeNames':layer,'resultType':'hits'})
        p=OUT/f'{stem}__hits.xml'; p.write_bytes(r.content)
        nm=parse_hits(r.content)
        row.update({'hits_http':r.status_code,'number_matched':nm,'hits_bytes':len(r.content),'hits_sha256':sha256_bytes(r.content)})
        manifest.append([p.name,len(r.content),sha256_bytes(r.content),r.url])
    except Exception as e:
        row['hits_error']=repr(e)
    try:
        r=get(s,{'service':'WFS','version':'2.0.0','request':'GetFeature','typeNames':layer,'count':'1','outputFormat':'application/json'})
        p=OUT/f'{stem}__sample.geojson'; p.write_bytes(r.content)
        js=r.json(); feats=js.get('features',[]); geom=(feats[0].get('geometry') or {}).get('type','') if feats else ''
        props=list((feats[0].get('properties') or {}).keys()) if feats else []
        row.update({'sample_http':r.status_code,'sample_feature_count':len(feats),'sample_geom_type':geom,'sample_property_count':len(props),'sample_properties':' | '.join(props),'sample_bytes':len(r.content),'sample_sha256':sha256_bytes(r.content)})
        manifest.append([p.name,len(r.content),sha256_bytes(r.content),r.url])
    except Exception as e:
        row['sample_error']=repr(e)
    rows.append(row)

cols=sorted({k for r in rows for k in r})
with open(OUT/'inventario_probe_l07.csv','w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=cols); w.writeheader(); w.writerows(rows)
with open(OUT/'manifesto_probe_l07.csv','w',newline='',encoding='utf-8-sig') as f:
    w=csv.writer(f); w.writerow(['arquivo','bytes','sha256','url_final']); w.writerows(manifest)
summary={
 'camadas_previstas':len(LAYERS),
 'describe_ok':sum(1 for r in rows if r.get('describe_http')==200),
 'hits_ok':sum(1 for r in rows if r.get('hits_http')==200),
 'sample_ok':sum(1 for r in rows if r.get('sample_http')==200),
 'counts':{r['layer_name']:r.get('number_matched','') for r in rows},
 'regra':'Este probe nao substitui o sub-snapshot integral. Serve para dimensionar coleta paginada e congelar esquema/cardinalidade antes da ingestao completa.'
}
(OUT/'resumo_probe_l07.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
if summary['describe_ok']<len(LAYERS) or summary['hits_ok']<len(LAYERS) or summary['sample_ok']<len(LAYERS):
    sys.exit(2)
