from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path('mg853-g5-normalize-l02/inventory_output')
RAW = ROOT / '00_SUBSNAPSHOT_OPERACIONAL'
EXT = ROOT / '01_EXTRAIDO'
AUDIT = ROOT / '02_INVENTARIO'
for p in (RAW, EXT, AUDIT): p.mkdir(parents=True, exist_ok=True)

SOURCES = {
    'AGUA_2024': 'https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/saneamento/sinisa/arquivos/SINISA_Resultados_Ref20242.zip',
    'GESTAO_MUNICIPAL_2023': 'https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/saneamento/sinisa/resultados-sinisa/SINISA_GESTAOMUNICIPAL_Informacoes_2023.xlsx',
    'ESGOTO_2023': 'https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/saneamento/sinisa/resultados-sinisa/SINISA_ESGOTO_Planilhas_2023_v2.zip',
    'RESIDUOS_2023': 'https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/saneamento/sinisa/resultados-sinisa/SINISA_RESIDUOS_Planilhas_2023.rar',
    'AGUAS_PLUVIAIS_2023': 'https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/saneamento/sinisa/resultados-sinisa/SINISA_AGUASPLUVIAIS_PLANILHAS_2023_V224042025.rar',
}


def sha256(path: Path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()


def download(key, url):
    suffix = '.xlsx' if url.lower().endswith('.xlsx') else '.zip' if url.lower().endswith('.zip') else '.rar'
    p=RAW/f'{key}{suffix}'
    req=urllib.request.Request(url, headers={'User-Agent':'MG853-OABMG/1.0','Accept-Encoding':'identity'})
    with urllib.request.urlopen(req, timeout=300) as r, p.open('wb') as f:
        while True:
            b=r.read(1024*1024)
            if not b: break
            f.write(b)
    return p


def extract_source(key: str, path: Path):
    out=EXT/key
    out.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower()=='.zip':
        with zipfile.ZipFile(path) as z: z.extractall(out)
    elif path.suffix.lower()=='.rar':
        cmd=None
        for c in ('7zz','7z'):
            if shutil.which(c): cmd=c; break
        if not cmd:
            raise RuntimeError('7z/7zz não disponível no runner')
        subprocess.run([cmd,'x','-y',f'-o{out}',str(path)], check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    else:
        shutil.copy2(path, out/path.name)
    return out


def xlsx_sheet_names(path: Path):
    ns={'a':'http://schemas.openxmlformats.org/spreadsheetml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
    with zipfile.ZipFile(path) as z:
        wb=ET.fromstring(z.read('xl/workbook.xml'))
        return [s.attrib['name'] for s in wb.find('a:sheets',ns)]


def parse_preview(path: Path, max_rows=30, max_cols=50):
    ns={'a':'http://schemas.openxmlformats.org/spreadsheetml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
    def col_i(ref):
        m=re.match(r'([A-Z]+)',ref); n=0
        for c in m.group(1): n=n*26+ord(c)-64
        return n-1
    result=[]
    with zipfile.ZipFile(path) as z:
        shared=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            rt=ET.fromstring(z.read('xl/sharedStrings.xml'))
            for si in rt.findall('a:si',ns): shared.append(''.join(t.text or '' for t in si.findall('.//a:t',ns)))
        wb=ET.fromstring(z.read('xl/workbook.xml'))
        rr=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        rel={x.attrib['Id']:x.attrib['Target'] for x in rr}
        for s in wb.find('a:sheets',ns):
            name=s.attrib['name']; rid=s.attrib['{'+ns['r']+'}id']; target=rel[rid]
            if not target.startswith('xl/'): target='xl/'+target.lstrip('/')
            rt=ET.fromstring(z.read(target))
            dim=rt.find('a:dimension',ns)
            dimension=dim.attrib.get('ref','') if dim is not None else ''
            rows=[]
            for row in rt.findall('.//a:sheetData/a:row',ns)[:max_rows]:
                vals={}
                for c in row.findall('a:c',ns):
                    idx=col_i(c.attrib['r'])
                    if idx>=max_cols: continue
                    typ=c.attrib.get('t'); v=c.find('a:v',ns)
                    val=''
                    if typ=='inlineStr': val=''.join(t.text or '' for t in c.findall('.//a:t',ns))
                    elif v is not None:
                        raw=v.text or ''; val=shared[int(raw)] if typ=='s' and raw else raw
                    vals[idx]=val
                if vals:
                    rows.append({'excel_row':int(row.attrib.get('r','0')), 'cells':[vals.get(i,'') for i in range(min(max_cols,max(vals)+1))]})
            result.append({'sheet':name,'dimension':dimension,'preview':rows})
    return result

manifest=[]
preview={}
for key,url in SOURCES.items():
    p=download(key,url)
    manifest.append({'source':key,'url':url,'filename':p.name,'size_bytes':p.stat().st_size,'sha256':sha256(p)})
    out=extract_source(key,p)
    books=sorted(out.rglob('*.xlsx'))
    preview[key]=[]
    for book in books:
        try:
            item={'file':str(book.relative_to(EXT)),'size_bytes':book.stat().st_size,'sha256':sha256(book),'sheets':parse_preview(book)}
        except Exception as e:
            item={'file':str(book.relative_to(EXT)),'size_bytes':book.stat().st_size,'sha256':sha256(book),'error':repr(e)}
        preview[key].append(item)

(AUDIT/'manifesto_fontes.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
(AUDIT/'inventario_xlsx.json').write_text(json.dumps(preview,ensure_ascii=False,indent=2),encoding='utf-8')
with (AUDIT/'manifesto_fontes.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=['source','url','filename','size_bytes','sha256'],delimiter=';');w.writeheader();w.writerows(manifest)
summary={'timestamp_utc':datetime.now(timezone.utc).replace(microsecond=0).isoformat(),'sources':len(manifest),'xlsx_files':sum(len(v) for v in preview.values()),'manifest':manifest}
(AUDIT/'resumo.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
for k,v in preview.items():
    print('\n###',k,'xlsx=',len(v))
    for b in v:
        print('FILE',b['file'])
        for s in b.get('sheets',[]):
            print('  SHEET',s['sheet'],'DIM',s['dimension'])
            for r in s['preview'][:8]: print('   ',r)
