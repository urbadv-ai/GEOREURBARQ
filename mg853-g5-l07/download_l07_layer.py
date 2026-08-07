from __future__ import annotations

import argparse, csv, hashlib, json, os, re, struct, sys, time, zipfile
from datetime import datetime, timezone
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from xml.etree import ElementTree as ET

BASE='https://geoserver.meioambiente.mg.gov.br/ows'
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

def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
def safe(s): return re.sub(r'[^A-Za-z0-9_.-]+','_',s)
def sha256_file(p:Path):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def sha256_bytes(b): return hashlib.sha256(b).hexdigest()

def session():
    retry=Retry(total=7,connect=7,read=6,status=6,backoff_factor=2,status_forcelist=(429,500,502,503,504),allowed_methods=frozenset({'GET'}),raise_on_status=False)
    s=requests.Session(); s.headers.update({'User-Agent':'MG853-G5-L07/1.0 OABMG research snapshot'})
    s.mount('https://',HTTPAdapter(max_retries=retry)); return s

def parse_hits(b):
    root=ET.fromstring(b)
    for k in ('numberMatched','numberOfFeatures'):
        if k in root.attrib:
            v=root.attrib[k]
            if v not in ('unknown',''):
                return int(v)
    raise RuntimeError('numberMatched ausente')

def dbf_count_from_zip(zp:Path):
    with zipfile.ZipFile(zp) as z:
        names=z.namelist()
        dbfs=[n for n in names if n.lower().endswith('.dbf')]
        if not dbfs: raise RuntimeError('DBF ausente')
        with z.open(dbfs[0]) as f:
            hdr=f.read(32)
            if len(hdr)<8: raise RuntimeError('DBF header incompleto')
            count=struct.unpack('<I',hdr[4:8])[0]
        required={'.shp','.shx','.dbf','.prj'}
        exts={Path(n).suffix.lower() for n in names}
        missing=sorted(required-exts)
        prjs=[n for n in names if n.lower().endswith('.prj')]
        prj_text=z.read(prjs[0]).decode('utf-8','replace') if prjs else ''
        return count,names,missing,prj_text

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--index',type=int,required=True); args=ap.parse_args()
    idx=args.index
    logical_id,group,layer=LAYERS[idx]
    stem=f'{idx:02d}_{safe(layer.replace(":","__"))}'
    out=Path('out_l07_subsnapshots')/stem; out.mkdir(parents=True,exist_ok=True)
    s=session()

    hits=s.get(BASE,params={'service':'WFS','version':'2.0.0','request':'GetFeature','typeNames':layer,'resultType':'hits'},timeout=(20,180),allow_redirects=True)
    hits.raise_for_status(); expected=parse_hits(hits.content)
    (out/'hits.xml').write_bytes(hits.content)

    desc=s.get(BASE,params={'service':'WFS','version':'2.0.0','request':'DescribeFeatureType','typeNames':layer},timeout=(20,180),allow_redirects=True)
    desc.raise_for_status(); (out/'DescribeFeatureType.xml').write_bytes(desc.content)

    zip_path=out/'raw_wfs_shape.zip'
    params={'service':'WFS','version':'2.0.0','request':'GetFeature','typeNames':layer,'outputFormat':'SHAPE-ZIP'}
    with s.get(BASE,params=params,stream=True,timeout=(30,1800),allow_redirects=True) as r:
        r.raise_for_status()
        ctype=r.headers.get('content-type','')
        with zip_path.open('wb') as f:
            for ch in r.iter_content(1024*1024):
                if ch: f.write(ch)
        final_url=r.url
        headers=dict(r.headers)
    if not zipfile.is_zipfile(zip_path):
        prefix=zip_path.read_bytes()[:1000]
        raise RuntimeError(f'Resposta nao ZIP; content-type={ctype}; prefix={prefix[:300]!r}')
    actual,names,missing,prj=dbf_count_from_zip(zip_path)
    ok=(actual==expected and not missing)
    manifest={
        'lote_id':'G5-L07','logical_id':logical_id,'grupo':group,'layer_index':idx,'layer_name':layer,
        'data_hora_utc':now(),'wfs_base':BASE,'expected_number_matched':expected,'dbf_record_count':actual,
        'count_confere':actual==expected,'required_components_missing':missing,'zip_members':names,
        'raw_zip_bytes':zip_path.stat().st_size,'raw_zip_sha256':sha256_file(zip_path),
        'hits_sha256':sha256_bytes(hits.content),'describe_sha256':sha256_bytes(desc.content),
        'final_url':final_url,'content_type':ctype,'response_headers':headers,'prj_text':prj,
        'status_subsnapshot':'COMPLETO' if ok else 'BLOQUEADO_QA',
        'regra_semantica':'Camada contextual; cobertura/presenca/area nao equivalem a desempenho, legalidade, risco ou conformidade.'
    }
    (out/'manifesto_subsnapshot.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    with open(out/'manifesto_subsnapshot.csv','w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=[k for k,v in manifest.items() if not isinstance(v,(dict,list))]); w.writeheader(); w.writerow({k:v for k,v in manifest.items() if not isinstance(v,(dict,list))})
    print(json.dumps({k:manifest[k] for k in ('layer_index','layer_name','expected_number_matched','dbf_record_count','raw_zip_bytes','raw_zip_sha256','status_subsnapshot')},ensure_ascii=False,indent=2))
    if not ok: sys.exit(2)

if __name__=='__main__': main()
