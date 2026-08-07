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

old_function = '''def csv_rows_from_zip(path: Path):
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.lower().endswith('.csv')]
        if len(names) != 1:
            raise RuntimeError(f'Esperado um CSV em {path.name}; encontrados {names}')
        with z.open(names[0]) as raw:
            text = io.TextIOWrapper(raw, encoding='utf-8-sig', newline='')
            yield from csv.DictReader(text, delimiter=';')
'''
new_function = '''def csv_rows_from_zip(path: Path):
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.lower().endswith('.csv')]
        if len(names) != 1:
            raise RuntimeError(f'Esperado um CSV em {path.name}; encontrados {names}')
        with z.open(names[0]) as raw:
            text = io.TextIOWrapper(raw, encoding='latin-1', newline='')
            reader = csv.reader(text, delimiter=';')
            headers = next(reader)
            # Preserva a chave oficial e apenas as variáveis formalmente admitidas.
            keep = [headers[0]] + [code for code in SELECTED if code in headers]
            indexes = [headers.index(code) for code in keep]
            for values in reader:
                yield {code: values[idx] for code, idx in zip(keep, indexes)}
'''
if old_function not in source:
    raise RuntimeError('Função original de leitura CSV não localizada')
source = source.replace(old_function, new_function, 1)
exec(compile(source, str(source_path), 'exec'), {'__name__': '__main__', '__file__': str(source_path)})
