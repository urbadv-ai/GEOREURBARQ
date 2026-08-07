from __future__ import annotations

import csv
import hashlib
import json
import re
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

OUT = Path('mg853-g5-normalize-l01/output_dictionary')
OUT.mkdir(parents=True, exist_ok=True)
URL = 'https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/dicionario_de_dados_agregados_por_setores_censitarios_20260520.xlsx'
XLSX = OUT / 'dicionario_de_dados_agregados_por_setores_censitarios_20260520.xlsx'

req = Request(URL, headers={'User-Agent': 'MG853-OABMG/1.0'})
with urlopen(req, timeout=180) as r, XLSX.open('wb') as f:
    while True:
        chunk = r.read(1024 * 1024)
        if not chunk:
            break
        f.write(chunk)

sha = hashlib.sha256(XLSX.read_bytes()).hexdigest()

NS = {'a': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
      'p': 'http://schemas.openxmlformats.org/package/2006/relationships'}


def col_index(cell_ref: str) -> int:
    letters = re.match(r'([A-Z]+)', cell_ref).group(1)
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1

with zipfile.ZipFile(XLSX) as z:
    shared = []
    if 'xl/sharedStrings.xml' in z.namelist():
        root = ET.fromstring(z.read('xl/sharedStrings.xml'))
        for si in root.findall('a:si', NS):
            shared.append(''.join(t.text or '' for t in si.findall('.//a:t', NS)))

    workbook = ET.fromstring(z.read('xl/workbook.xml'))
    rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
    relmap = {x.attrib['Id']: x.attrib['Target'] for x in rels}
    manifest = []
    for sheet in workbook.find('a:sheets', NS):
        name = sheet.attrib['name']
        rid = sheet.attrib['{'+NS['r']+'}id']
        target = relmap[rid]
        if not target.startswith('xl/'):
            target = 'xl/' + target.lstrip('/')
        root = ET.fromstring(z.read(target))
        rows_out = []
        max_col = 0
        for row in root.findall('.//a:sheetData/a:row', NS):
            vals = {}
            for c in row.findall('a:c', NS):
                idx = col_index(c.attrib['r'])
                max_col = max(max_col, idx)
                typ = c.attrib.get('t')
                v = c.find('a:v', NS)
                value = ''
                if typ == 'inlineStr':
                    value = ''.join(t.text or '' for t in c.findall('.//a:t', NS))
                elif v is not None:
                    raw = v.text or ''
                    value = shared[int(raw)] if typ == 's' and raw else raw
                vals[idx] = value
            if vals:
                rows_out.append([vals.get(i, '') for i in range(max_col + 1)])
        safe = re.sub(r'[^A-Za-z0-9_-]+', '_', name).strip('_') or 'sheet'
        csv_path = OUT / f'{safe}.csv'
        with csv_path.open('w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f, delimiter=';')
            w.writerows(rows_out)
        manifest.append({'sheet': name, 'csv': csv_path.name, 'rows': len(rows_out), 'columns': max_col + 1})

(OUT / 'manifesto_dicionario.json').write_text(json.dumps({
    'url': URL,
    'file': XLSX.name,
    'size_bytes': XLSX.stat().st_size,
    'sha256': sha,
    'sheets': manifest,
}, ensure_ascii=False, indent=2), encoding='utf-8')

with (OUT / 'manifesto_dicionario.csv').open('w', newline='', encoding='utf-8-sig') as f:
    w = csv.DictWriter(f, fieldnames=['sheet', 'csv', 'rows', 'columns'], delimiter=';')
    w.writeheader(); w.writerows(manifest)

print(json.dumps({'sha256': sha, 'size': XLSX.stat().st_size, 'sheets': manifest}, ensure_ascii=False, indent=2))
