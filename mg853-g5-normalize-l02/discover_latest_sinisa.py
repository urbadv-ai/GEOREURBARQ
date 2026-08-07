from __future__ import annotations

import hashlib
import json
import os
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('mg853-g5-normalize-l02/discovery_output')
ROOT.mkdir(parents=True, exist_ok=True)
URL = 'https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/saneamento/sinisa/arquivos/SINISA_Resultados_Ref20242.zip'
OUT = ROOT / 'SINISA_Resultados_Ref20242.zip'
req = urllib.request.Request(URL, headers={'User-Agent':'MG853-OABMG/1.0','Accept-Encoding':'identity'})
with urllib.request.urlopen(req, timeout=300) as r, OUT.open('wb') as f:
    while True:
        chunk = r.read(1024*1024)
        if not chunk:
            break
        f.write(chunk)

h=hashlib.sha256()
with OUT.open('rb') as f:
    for chunk in iter(lambda:f.read(1024*1024), b''):
        h.update(chunk)

with zipfile.ZipFile(OUT) as z:
    names=z.namelist()
    manifest=[]
    for info in z.infolist():
        manifest.append({'path':info.filename,'size':info.file_size,'compressed_size':info.compress_size})

meta={
    'source_url':URL,
    'downloaded_at_utc':datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    'size_bytes':OUT.stat().st_size,
    'sha256':h.hexdigest(),
    'entries':len(names),
    'paths':manifest,
}
(ROOT/'discovery.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(meta, ensure_ascii=False, indent=2))
