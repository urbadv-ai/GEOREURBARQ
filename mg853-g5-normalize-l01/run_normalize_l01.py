from __future__ import annotations

from pathlib import Path

source_path = Path(__file__).with_name('normalize_l01.py')
source = source_path.read_text(encoding='utf-8')
source = source.replace(
    "import hashlib\n",
    "import hashlib\nimport gzip\n",
    1,
)
old_api = "api_data = json.loads(paths['municipios_api'].read_text(encoding='utf-8'))"
new_api = "_api_bytes = paths['municipios_api'].read_bytes()\nif _api_bytes[:2] == b'\\x1f\\x8b':\n    _api_bytes = gzip.decompress(_api_bytes)\napi_data = json.loads(_api_bytes.decode('utf-8'))"
if old_api not in source:
    raise RuntimeError('Ponto de reparação da resposta da API não localizado')
source = source.replace(old_api, new_api, 1)
old_csv = "text = io.TextIOWrapper(raw, encoding='utf-8-sig', newline='')"
new_csv = "text = io.TextIOWrapper(raw, encoding='latin-1', newline='')"
if old_csv not in source:
    raise RuntimeError('Ponto de reparação da codificação CSV não localizado')
source = source.replace(old_csv, new_csv, 1)
exec(compile(source, str(source_path), 'exec'), {'__name__': '__main__', '__file__': str(source_path)})
