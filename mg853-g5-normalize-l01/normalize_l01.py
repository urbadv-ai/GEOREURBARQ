from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import time
import zipfile
from collections import OrderedDict, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

ROOT = Path('mg853-g5-normalize-l01/output_normalization')
RAW = ROOT / '00_SUBSNAPSHOT_OPERACIONAL'
OUT = ROOT / '01_BASE_NORMALIZADA'
AUDIT = ROOT / '02_AUDITORIA'
for p in (RAW, OUT, AUDIT):
    p.mkdir(parents=True, exist_ok=True)

NOW = datetime.now(timezone.utc).replace(microsecond=0)
DATE = NOW.date().isoformat().replace('-', '')
SOURCE_BASE = 'https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios'
URLS = {
    'setor2': SOURCE_BASE + '/Agregados_por_Setor_csv/Agregados_por_setores_caracteristicas_domicilio2_BR_20250417.zip',
    'setor3': SOURCE_BASE + '/Agregados_por_Setor_csv/Agregados_por_setores_caracteristicas_domicilio3_BR_20250417.zip',
    'municipio2': SOURCE_BASE + '/Agregados_por_Municipio_csv/Agregados_por_municipios_caracteristicas_domicilio2_BR_20250417.zip',
    'municipio3': SOURCE_BASE + '/Agregados_por_Municipio_csv/Agregados_por_municipios_caracteristicas_domicilio3_BR_20250417.zip',
    'dicionario': SOURCE_BASE + '/dicionario_de_dados_agregados_por_setores_censitarios_20260520.xlsx',
    'municipios_api': 'https://servicodados.ibge.gov.br/api/v1/localidades/estados/31/municipios?orderBy=nome',
}
EXPECTED_SECTOR_HASHES = {
    'setor2': '513f8a0d9c84b1325487f651f6d5d90bbc6f5ad7af60460b53598555ac008759',
    'setor3': 'f38010582b8329f4b3d63708f3e8aae3b8df1c1b471398b2c67f5ef3ad1ba5c7',
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def download(key: str, filename: str, required: bool = True) -> Path:
    url = URLS[key]
    path = RAW / filename
    last = None
    for attempt in range(1, 7):
        try:
            req = Request(url, headers={'User-Agent': 'MG853-OABMG/1.0'})
            with urlopen(req, timeout=240) as r, path.open('wb') as f:
                while True:
                    chunk = r.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
            return path
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last = exc
            if path.exists():
                path.unlink()
            time.sleep(min(30, attempt * 3))
    if required:
        raise RuntimeError(f'Falha ao baixar {key}: {last}')
    return path


def parse_xlsx_sheets(path: Path) -> dict[str, list[list[str]]]:
    ns = {'a': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
          'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}

    def col_index(ref: str) -> int:
        letters = re.match(r'([A-Z]+)', ref).group(1)
        n = 0
        for ch in letters:
            n = n * 26 + ord(ch) - 64
        return n - 1

    with zipfile.ZipFile(path) as z:
        shared = []
        if 'xl/sharedStrings.xml' in z.namelist():
            root = ET.fromstring(z.read('xl/sharedStrings.xml'))
            for si in root.findall('a:si', ns):
                shared.append(''.join(t.text or '' for t in si.findall('.//a:t', ns)))
        workbook = ET.fromstring(z.read('xl/workbook.xml'))
        relroot = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        relmap = {x.attrib['Id']: x.attrib['Target'] for x in relroot}
        result = {}
        for sheet in workbook.find('a:sheets', ns):
            name = sheet.attrib['name']
            rid = sheet.attrib['{'+ns['r']+'}id']
            target = relmap[rid]
            if not target.startswith('xl/'):
                target = 'xl/' + target.lstrip('/')
            root = ET.fromstring(z.read(target))
            rows = []
            for row in root.findall('.//a:sheetData/a:row', ns):
                vals = {}
                max_col = -1
                for c in row.findall('a:c', ns):
                    idx = col_index(c.attrib['r'])
                    max_col = max(max_col, idx)
                    typ = c.attrib.get('t')
                    v = c.find('a:v', ns)
                    value = ''
                    if typ == 'inlineStr':
                        value = ''.join(t.text or '' for t in c.findall('.//a:t', ns))
                    elif v is not None:
                        raw = v.text or ''
                        value = shared[int(raw)] if typ == 's' and raw else raw
                    vals[idx] = value
                if max_col >= 0:
                    rows.append([vals.get(i, '') for i in range(max_col + 1)])
            result[name] = rows
        return result


# Códigos deliberadamente restritos às condições objetivas de saneamento e habitação.
SELECTED = OrderedDict()

def add(code: str, alias: str, dimension: str, observation: str, group: str, order: int):
    SELECTED[code] = {
        'alias': alias, 'dimension': dimension, 'observation': observation,
        'group': group, 'order': order,
    }

water_dom = [
    ('V00111','dom_agua_rede_geral'),('V00112','dom_agua_poco_profundo'),
    ('V00113','dom_agua_poco_raso'),('V00114','dom_agua_fonte_nascente'),
    ('V00115','dom_agua_carro_pipa'),('V00116','dom_agua_chuva_armazenada'),
    ('V00117','dom_agua_corpo_hidrico'),('V00118','dom_agua_outra_forma')]
bath_dom = [
    ('V00232','dom_banheiro_exclusivo_1'),('V00233','dom_banheiro_exclusivo_2'),
    ('V00234','dom_banheiro_exclusivo_3'),('V00235','dom_banheiro_exclusivo_4_ou_mais'),
    ('V00236','dom_apenas_banheiro_comum'),('V00237','dom_apenas_sanitario_ou_buraco'),
    ('V00238','dom_sem_banheiro_nem_sanitario')]
sewage_dom = [
    ('V00309','dom_esgoto_rede_geral_ou_pluvial'),('V00310','dom_esgoto_fossa_septica_ligada_rede'),
    ('V00311','dom_esgoto_fossa_septica_nao_ligada'),('V00312','dom_esgoto_fossa_rudimentar_ou_buraco'),
    ('V00313','dom_esgoto_vala'),('V00314','dom_esgoto_rio_lago_corrego_mar'),
    ('V00315','dom_esgoto_outra_forma'),('V00316','dom_esgoto_inexistente_sem_banheiro')]
waste_dom = [
    ('V00397','dom_lixo_coletado_domicilio'),('V00398','dom_lixo_cacamba_servico'),
    ('V00399','dom_lixo_queimado'),('V00400','dom_lixo_enterrado'),
    ('V00401','dom_lixo_terreno_baldio_area_publica'),('V00402','dom_lixo_outro_destino')]
connection_dom = [('V00463','dom_ligado_rede_mas_usa_outra_fonte'),('V00464','dom_sem_ligacao_rede_agua')]
control_dom = [('V00494','ctrl_dom_com_banheiro_exclusivo'),('V00495','ctrl_dom_sem_banheiro_exclusivo')]
water_mor = [(f'V{n:05d}', a.replace('dom_', 'mor_')) for (n,a) in [(508,'dom_agua_rede_geral'),(509,'dom_agua_poco_profundo'),(510,'dom_agua_poco_raso'),(511,'dom_agua_fonte_nascente'),(512,'dom_agua_carro_pipa'),(513,'dom_agua_chuva_armazenada'),(514,'dom_agua_corpo_hidrico'),(515,'dom_agua_outra_forma')]]
bath_mor = [(f'V{n:05d}', a) for n,a in [
    (552,'mor_banheiro_exclusivo_1'),(553,'mor_banheiro_exclusivo_2'),(554,'mor_banheiro_exclusivo_3'),
    (555,'mor_banheiro_exclusivo_4_ou_mais'),(556,'mor_apenas_banheiro_comum'),
    (557,'mor_apenas_sanitario_ou_buraco'),(558,'mor_sem_banheiro_nem_sanitario')]]
sewage_mor = [(f'V{n:05d}', a) for n,a in [
    (580,'mor_esgoto_rede_geral_ou_pluvial'),(581,'mor_esgoto_fossa_septica_ligada_rede'),
    (582,'mor_esgoto_fossa_septica_nao_ligada'),(583,'mor_esgoto_fossa_rudimentar_ou_buraco'),
    (584,'mor_esgoto_vala'),(585,'mor_esgoto_rio_lago_corrego_mar'),
    (586,'mor_esgoto_outra_forma'),(587,'mor_esgoto_inexistente_sem_banheiro')]]
waste_mor = [(f'V{n:05d}', a) for n,a in [
    (612,'mor_lixo_coletado_domicilio'),(613,'mor_lixo_cacamba_servico'),(614,'mor_lixo_queimado'),
    (615,'mor_lixo_enterrado'),(616,'mor_lixo_terreno_baldio_area_publica'),(617,'mor_lixo_outro_destino')]]
connection_mor = [('V00636','mor_ligado_rede_mas_usa_outra_fonte'),('V00637','mor_sem_ligacao_rede_agua')]

for order, (code, alias) in enumerate(water_dom, 1): add(code,alias,'SANEAMENTO_AGUA','DOMICILIO','DOM_AGUA',order)
for order, (code, alias) in enumerate(bath_dom, 1): add(code,alias,'CONDICAO_SANITARIA','DOMICILIO','DOM_BANHEIRO',order)
for order, (code, alias) in enumerate(sewage_dom, 1): add(code,alias,'SANEAMENTO_ESGOTO','DOMICILIO','DOM_ESGOTO',order)
for order, (code, alias) in enumerate(waste_dom, 1): add(code,alias,'RESIDUOS_SOLIDOS','DOMICILIO','DOM_LIXO',order)
for order, (code, alias) in enumerate(connection_dom, 1): add(code,alias,'INFRAESTRUTURA_AGUA','DOMICILIO','DOM_LIGACAO_AGUA',order)
for order, (code, alias) in enumerate(control_dom, 1): add(code,alias,'CONTROLE_UNIVERSO','DOMICILIO','CTRL_BANHEIRO',order)
for order, (code, alias) in enumerate(water_mor, 1): add(code,alias,'SANEAMENTO_AGUA','MORADOR','MOR_AGUA',order)
for order, (code, alias) in enumerate(bath_mor, 1): add(code,alias,'CONDICAO_SANITARIA','MORADOR','MOR_BANHEIRO',order)
for order, (code, alias) in enumerate(sewage_mor, 1): add(code,alias,'SANEAMENTO_ESGOTO','MORADOR','MOR_ESGOTO',order)
for order, (code, alias) in enumerate(waste_mor, 1): add(code,alias,'RESIDUOS_SOLIDOS','MORADOR','MOR_LIXO',order)
for order, (code, alias) in enumerate(connection_mor, 1): add(code,alias,'INFRAESTRUTURA_AGUA','MORADOR','MOR_LIGACAO_AGUA',order)

GROUP_CODES = defaultdict(list)
for code, meta in SELECTED.items():
    GROUP_CODES[meta['group']].append(code)


def to_number(value: str):
    value = (value or '').strip()
    if value in ('', 'X', 'x', '-', '..', '...'):
        return None
    try:
        return int(value)
    except ValueError:
        try:
            return float(value.replace(',', '.'))
        except ValueError:
            return None


def pct(num, den):
    if num is None or den in (None, 0):
        return None
    return round(100.0 * num / den, 6)


def sum_codes(row: dict, codes: list[str]):
    vals = [row.get(c) for c in codes]
    if any(v is None for v in vals):
        return None
    return sum(vals)


def csv_rows_from_zip(path: Path):
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.lower().endswith('.csv')]
        if len(names) != 1:
            raise RuntimeError(f'Esperado um CSV em {path.name}; encontrados {names}')
        with z.open(names[0]) as raw:
            text = io.TextIOWrapper(raw, encoding='utf-8-sig', newline='')
            yield from csv.DictReader(text, delimiter=';')


# 1) Aquisição e verificação da cadeia de custódia.
paths = {
    'setor2': download('setor2', 'Agregados_por_setores_caracteristicas_domicilio2_BR_20250417.zip'),
    'setor3': download('setor3', 'Agregados_por_setores_caracteristicas_domicilio3_BR_20250417.zip'),
    'municipio2': download('municipio2', 'Agregados_por_municipios_caracteristicas_domicilio2_BR_20250417.zip'),
    'municipio3': download('municipio3', 'Agregados_por_municipios_caracteristicas_domicilio3_BR_20250417.zip'),
    'dicionario': download('dicionario', 'dicionario_de_dados_agregados_por_setores_censitarios_20260520.xlsx'),
    'municipios_api': download('municipios_api', 'municipios_mg_api_ibge_20260807.json'),
}
hashes = {k: sha256(v) for k,v in paths.items()}
for k, expected in EXPECTED_SECTOR_HASHES.items():
    if hashes[k] != expected:
        raise RuntimeError(f'Hash divergente para {k}: {hashes[k]} != {expected}')

# 2) Dicionário oficial e validação dos códigos selecionados.
sheets = parse_xlsx_sheets(paths['dicionario'])
dict_rows = sheets.get('Dicionário não PCT')
if not dict_rows:
    raise RuntimeError('Aba Dicionário não PCT não localizada')
headers = dict_rows[0]
desc_map = {}
for vals in dict_rows[1:]:
    row = dict(zip(headers, vals))
    code = row.get('Variável', '')
    if code:
        desc_map[code] = row
missing_dict = [c for c in SELECTED if c not in desc_map]
if missing_dict:
    raise RuntimeError(f'Códigos ausentes no dicionário: {missing_dict}')

# 3) Base oficial de municípios MG.
api_data = json.loads(paths['municipios_api'].read_text(encoding='utf-8'))
municipios = {str(x['id']).zfill(7): x['nome'] for x in api_data}
if len(municipios) != 853:
    raise RuntimeError(f'API oficial retornou {len(municipios)} municípios, esperado 853')

# 4) Leitura da base municipal oficial. Ela prevalece sobre soma setorial quando há X.
municipal_raw = {}
municipal_source_presence = defaultdict(set)
for source_key in ('municipio2','municipio3'):
    for r in csv_rows_from_zip(paths[source_key]):
        code_field = next((x for x in r if x.lower() in ('municipio','município','codigo_municipio','cod_municipio')), None)
        if code_field is None:
            code_field = list(r)[0]
        cod = (r.get(code_field) or '').strip().strip('"').zfill(7)
        if not cod.startswith('31'):
            continue
        municipal_raw.setdefault(cod, {})
        for var in SELECTED:
            if var in r:
                municipal_raw[cod][var] = to_number(r[var])
                if (r[var] or '').strip().upper() == 'X':
                    municipal_source_presence[cod].add(var)

# 5) Verificação independente por soma setorial e controle das supressões X.
sector_sum = {cod: defaultdict(int) for cod in municipios}
sector_x = {cod: defaultdict(int) for cod in municipios}
sector_rows = {cod: 0 for cod in municipios}
for source_key in ('setor2','setor3'):
    for r in csv_rows_from_zip(paths[source_key]):
        code_field = next((x for x in r if x.lower() == 'setor'), list(r)[0])
        setor = (r.get(code_field) or '').strip()
        if not setor.startswith('31'):
            continue
        cod = setor[:7]
        if cod not in municipios:
            continue
        sector_rows[cod] += 1
        for var in SELECTED:
            if var not in r:
                continue
            raw = (r[var] or '').strip()
            if raw.upper() == 'X':
                sector_x[cod][var] += 1
            else:
                val = to_number(raw)
                if val is not None:
                    sector_sum[cod][var] += val

# 6) Estrutura normalizada e indicadores derivados.
base_rows = []
long_rows = []
comparison_rows = []
coverage_var = []

DERIVED_META = OrderedDict([
    ('pct_dom_agua_rede_geral', ('V00111','DEN_DOM_AGUA','Domicílios que utilizam rede geral de distribuição (%)')),
    ('pct_dom_agua_pocos', (['V00112','V00113'],'DEN_DOM_AGUA','Domicílios que utilizam poço profundo ou raso (%)')),
    ('pct_dom_agua_nascente_ou_corpo_hidrico', (['V00114','V00117'],'DEN_DOM_AGUA','Domicílios que utilizam fonte/nascente ou corpo hídrico (%)')),
    ('pct_dom_agua_carro_pipa_chuva_ou_outra', (['V00115','V00116','V00118'],'DEN_DOM_AGUA','Domicílios com carro-pipa, água da chuva ou outra forma (%)')),
    ('pct_dom_sem_ligacao_rede_agua', ('V00464','DEN_DOM_AGUA','Domicílios sem ligação à rede geral de água (%)')),
    ('pct_dom_sem_banheiro_exclusivo', ('V00495','DEN_DOM_BANHEIRO_CTRL','Domicílios sem banheiro exclusivo (%)')),
    ('pct_dom_sem_banheiro_nem_sanitario', ('V00238','DEN_DOM_BANHEIRO','Domicílios sem banheiro nem sanitário (%)')),
    ('pct_dom_esgoto_rede_geral_ou_pluvial', ('V00309','DEN_DOM_ESGOTO','Domicílios com destinação em rede geral ou pluvial (%)')),
    ('pct_dom_esgoto_fossa_septica_total', (['V00310','V00311'],'DEN_DOM_ESGOTO','Domicílios com fossa séptica/filtro (%)')),
    ('pct_dom_esgoto_fossa_rudimentar_vala_ou_corpo_hidrico', (['V00312','V00313','V00314'],'DEN_DOM_ESGOTO','Domicílios com fossa rudimentar, vala ou corpo hídrico (%)')),
    ('pct_dom_esgoto_inexistente_sem_banheiro', ('V00316','DEN_DOM_ESGOTO','Domicílios sem destinação por ausência de banheiro/sanitário (%)')),
    ('pct_dom_lixo_servico_limpeza', (['V00397','V00398'],'DEN_DOM_LIXO','Domicílios com lixo coletado ou depositado em caçamba de serviço (%)')),
    ('pct_dom_lixo_queimado', ('V00399','DEN_DOM_LIXO','Domicílios com lixo queimado na propriedade (%)')),
    ('pct_dom_lixo_outros_destinos', (['V00400','V00401','V00402'],'DEN_DOM_LIXO','Domicílios com lixo enterrado, lançado em área pública ou outro destino (%)')),
    ('pct_mor_agua_rede_geral', ('V00508','DEN_MOR_AGUA','Moradores em domicílios que utilizam rede geral (%)')),
    ('pct_mor_agua_pocos', (['V00509','V00510'],'DEN_MOR_AGUA','Moradores em domicílios que utilizam poços (%)')),
    ('pct_mor_sem_banheiro_exclusivo', (['V00556','V00557','V00558'],'DEN_MOR_BANHEIRO','Moradores em domicílios sem banheiro exclusivo (%)')),
    ('pct_mor_sem_banheiro_nem_sanitario', ('V00558','DEN_MOR_BANHEIRO','Moradores em domicílios sem banheiro nem sanitário (%)')),
    ('pct_mor_esgoto_rede_geral_ou_pluvial', ('V00580','DEN_MOR_ESGOTO','Moradores em domicílios com destinação em rede geral ou pluvial (%)')),
    ('pct_mor_esgoto_fossa_septica_total', (['V00581','V00582'],'DEN_MOR_ESGOTO','Moradores em domicílios com fossa séptica/filtro (%)')),
    ('pct_mor_esgoto_fossa_rudimentar_vala_ou_corpo_hidrico', (['V00583','V00584','V00585'],'DEN_MOR_ESGOTO','Moradores em domicílios com fossa rudimentar, vala ou corpo hídrico (%)')),
    ('pct_mor_lixo_servico_limpeza', (['V00612','V00613'],'DEN_MOR_LIXO','Moradores em domicílios com lixo coletado ou em caçamba de serviço (%)')),
    ('pct_mor_lixo_queimado', ('V00614','DEN_MOR_LIXO','Moradores em domicílios com lixo queimado (%)')),
    ('pct_mor_sem_ligacao_rede_agua', ('V00637','DEN_MOR_AGUA','Moradores em domicílios sem ligação à rede geral de água (%)')),
])

for cod, nome in sorted(municipios.items()):
    vals = municipal_raw.get(cod, {})
    raw_missing = [v for v in SELECTED if vals.get(v) is None]
    status = 'COMPLETA' if not raw_missing else 'PARCIAL_NI_ND'
    confidence = 'ALTO' if not raw_missing else 'ALTO_COM_RESSALVA'
    den = {
        'DEN_DOM_AGUA': sum_codes(vals, GROUP_CODES['DOM_AGUA']),
        'DEN_DOM_BANHEIRO': sum_codes(vals, GROUP_CODES['DOM_BANHEIRO']),
        'DEN_DOM_BANHEIRO_CTRL': sum_codes(vals, GROUP_CODES['CTRL_BANHEIRO']),
        'DEN_DOM_ESGOTO': sum_codes(vals, GROUP_CODES['DOM_ESGOTO']),
        'DEN_DOM_LIXO': sum_codes(vals, GROUP_CODES['DOM_LIXO']),
        'DEN_MOR_AGUA': sum_codes(vals, GROUP_CODES['MOR_AGUA']),
        'DEN_MOR_BANHEIRO': sum_codes(vals, GROUP_CODES['MOR_BANHEIRO']),
        'DEN_MOR_ESGOTO': sum_codes(vals, GROUP_CODES['MOR_ESGOTO']),
        'DEN_MOR_LIXO': sum_codes(vals, GROUP_CODES['MOR_LIXO']),
    }
    out = OrderedDict([
        ('cod_ibge_7', cod), ('municipio', nome), ('uf', 'MG'), ('ano_base', 2022),
        ('data_extracao', NOW.isoformat()), ('fonte_id', 'F-013'),
        ('ativo_origem', 'SNP-G5-L01-20260807;SSNP-G5-L01-MUN-20260807'),
        ('versao_transformacao', 'G5-L01-NORM-V1.0'), ('unidade_observacao', 'MUNICIPIO'),
        ('status_cobertura', status), ('status_registro', 'OK' if vals else 'ND'),
        ('nivel_confianca', confidence),
        ('observacao_auditoria', '' if not raw_missing else f'{len(raw_missing)} variáveis sem valor oficial numérico'),
        ('setores_com_moradores_nos_arquivos', sector_rows.get(cod, 0)),
    ])
    for code, meta in SELECTED.items():
        out[meta['alias']] = vals.get(code)
    for key, value in den.items():
        out[key.lower()] = value

    dom_den_values = [den[k] for k in ('DEN_DOM_AGUA','DEN_DOM_BANHEIRO','DEN_DOM_ESGOTO','DEN_DOM_LIXO') if den[k] is not None]
    mor_den_values = [den[k] for k in ('DEN_MOR_AGUA','DEN_MOR_BANHEIRO','DEN_MOR_ESGOTO','DEN_MOR_LIXO') if den[k] is not None]
    out['controle_amplitude_den_dom'] = max(dom_den_values)-min(dom_den_values) if dom_den_values else None
    out['controle_amplitude_den_mor'] = max(mor_den_values)-min(mor_den_values) if mor_den_values else None
    out['controle_banheiro_soma_vs_total'] = (den['DEN_DOM_BANHEIRO'] - den['DEN_DOM_BANHEIRO_CTRL']) if den['DEN_DOM_BANHEIRO'] is not None and den['DEN_DOM_BANHEIRO_CTRL'] is not None else None

    for metric, (numerator, denominator, label) in DERIVED_META.items():
        codes = numerator if isinstance(numerator, list) else [numerator]
        nums = [vals.get(c) for c in codes]
        num = None if any(v is None for v in nums) else sum(nums)
        out[metric] = pct(num, den[denominator])
        long_rows.append({
            'cod_ibge_7': cod, 'municipio': nome, 'uf': 'MG', 'ano_base': 2022,
            'indicador_id': metric, 'indicador': label, 'valor': out[metric],
            'unidade_medida': 'PERCENTUAL', 'denominador_id': denominator,
            'denominador_valor': den[denominator], 'fonte_id': 'F-013',
            'versao_transformacao': 'G5-L01-NORM-V1.0',
            'status_registro': 'OK' if out[metric] is not None else 'NI',
            'nivel_confianca': confidence,
            'observacao': 'Indicador descritivo; não constitui classificação jurídica ou de conformidade.'
        })
    base_rows.append(out)

    for var, meta in SELECTED.items():
        mval = vals.get(var)
        sval = sector_sum[cod].get(var, 0)
        xcount = sector_x[cod].get(var, 0)
        if mval is None:
            result = 'MUNICIPAL_NI_ND'
        elif xcount == 0 and sval == mval:
            result = 'IGUAL_SEM_SUPRESSAO'
        elif xcount > 0 and sval <= mval:
            result = 'COERENTE_COM_SUPRESSAO_SETORIAL'
        elif sval != mval:
            result = 'DIVERGENCIA'
        else:
            result = 'OK'
        comparison_rows.append({
            'cod_ibge_7': cod, 'municipio': nome, 'variavel': var,
            'campo_normalizado': meta['alias'], 'valor_municipal_oficial': mval,
            'soma_setorial_numerica': sval, 'setores_com_X': xcount,
            'residuo_municipal_menos_soma_setorial': None if mval is None else mval-sval,
            'resultado': result,
        })

# 7) Relatórios de cobertura e testes.
for var, meta in SELECTED.items():
    numeric = sum(1 for cod in municipios if municipal_raw.get(cod, {}).get(var) is not None)
    suppressed = sum(1 for cod in municipios if var in municipal_source_presence.get(cod, set()))
    coverage_var.append({
        'variavel': var, 'campo_normalizado': meta['alias'], 'dimensao': meta['dimension'],
        'unidade_observacao': meta['observation'], 'descricao_oficial': desc_map[var]['Descrição'],
        'municipios_com_valor_numerico': numeric, 'municipios_NI_ND': 853-numeric,
        'municipios_com_X_no_arquivo_municipal': suppressed,
        'cobertura_percentual': round(100*numeric/853,6),
        'decisao': 'INCLUIR_NUCLEO' if meta['observation'] == 'DOMICILIO' else 'INCLUIR_COM_RESSALVA',
    })

anomalous_comparisons = [r for r in comparison_rows if r['resultado'] == 'DIVERGENCIA']
percent_fields = list(DERIVED_META)
percent_out_of_range = 0
for row in base_rows:
    for f in percent_fields:
        v = row[f]
        if v is not None and not (0 <= v <= 100):
            percent_out_of_range += 1

tests = [
    ('L01-T01','API_MUNICIPIOS_853',len(municipios)==853,len(municipios),'Esperado 853'),
    ('L01-T02','BASE_MUNICIPAL_853',len(base_rows)==853,len(base_rows),'Esperado 853'),
    ('L01-T03','CHAVES_UNICAS',len({r['cod_ibge_7'] for r in base_rows})==853,len({r['cod_ibge_7'] for r in base_rows}),'Esperado 853'),
    ('L01-T04','PREFIXO_31',all(r['cod_ibge_7'].startswith('31') for r in base_rows),sum(r['cod_ibge_7'].startswith('31') for r in base_rows),'Esperado 853'),
    ('L01-T05','CODIGO_7_DIGITOS',all(len(r['cod_ibge_7'])==7 for r in base_rows),sum(len(r['cod_ibge_7'])==7 for r in base_rows),'Esperado 853'),
    ('L01-T06','HASH_SETOR2_PRIMARIO',hashes['setor2']==EXPECTED_SECTOR_HASHES['setor2'],hashes['setor2'],EXPECTED_SECTOR_HASHES['setor2']),
    ('L01-T07','HASH_SETOR3_PRIMARIO',hashes['setor3']==EXPECTED_SECTOR_HASHES['setor3'],hashes['setor3'],EXPECTED_SECTOR_HASHES['setor3']),
    ('L01-T08','DICIONARIO_64_VARIAVEIS',len(SELECTED)==64,len(SELECTED),'Esperado 64'),
    ('L01-T09','PERCENTUAIS_NA_FAIXA',percent_out_of_range==0,percent_out_of_range,'Esperado 0'),
    ('L01-T10','COMPARACAO_SETOR_MUNICIPIO_SEM_DIVERGENCIA',len(anomalous_comparisons)==0,len(anomalous_comparisons),'Esperado 0'),
]

# 8) Escrita dos produtos em UTF-8 BOM e separador ponto e vírgula.
def write_csv(path: Path, rows: list[dict], fields=None):
    if fields is None:
        fields = list(rows[0]) if rows else []
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=';', extrasaction='ignore')
        w.writeheader(); w.writerows(rows)

write_csv(OUT / 'MG853_G5_L01_BASE_MUNICIPAL_NORMALIZADA_V1_0.csv', base_rows)
write_csv(OUT / 'MG853_G5_L01_INDICADORES_LONGOS_V1_0.csv', long_rows)
write_csv(OUT / 'MG853_G5_L01_DICIONARIO_VARIAVEIS_V1_0.csv', [
    {
        'variavel_original': code, 'campo_normalizado': meta['alias'],
        'tema_oficial': desc_map[code]['Tema'], 'descricao_oficial': desc_map[code]['Descrição'],
        'dimensao': meta['dimension'], 'unidade_observacao': meta['observation'],
        'unidade_medida': 'CONTAGEM', 'ano_base': 2022, 'fonte_id': 'F-013',
        'decisao_admissao': 'INCLUIR_NUCLEO' if meta['observation']=='DOMICILIO' else 'INCLUIR_COM_RESSALVA',
        'regra_ausencia': 'X/blank => NI ou ND; nunca zero',
    } for code, meta in SELECTED.items()
])
write_csv(OUT / 'MG853_G5_L01_DICIONARIO_INDICADORES_DERIVADOS_V1_0.csv', [
    {'indicador_id': k, 'descricao': v[2], 'numerador_codigos': '|'.join(v[0] if isinstance(v[0],list) else [v[0]]),
     'denominador_id': v[1], 'unidade_medida': 'PERCENTUAL', 'formula': '100*numerador/denominador',
     'regra_ausencia': 'não calcular se numerador ou denominador não disponível'}
    for k,v in DERIVED_META.items()
])
write_csv(AUDIT / 'MG853_G5_L01_COBERTURA_VARIAVEIS_V1_0.csv', coverage_var)
write_csv(AUDIT / 'MG853_G5_L01_COMPARACAO_SETOR_MUNICIPIO_V1_0.csv', comparison_rows)
write_csv(AUDIT / 'MG853_G5_L01_TESTES_V1_0.csv', [
    {'teste_id': tid, 'teste': name, 'aprovado': 'SIM' if ok else 'NAO', 'resultado': result, 'esperado': expected}
    for tid,name,ok,result,expected in tests
])

# Manifesto do sub-snapshot e checksums dos produtos.
manifest = []
for path in sorted(ROOT.rglob('*')):
    if path.is_file():
        manifest.append({
            'relative_path': str(path.relative_to(ROOT)), 'file_name': path.name,
            'size_bytes': path.stat().st_size, 'sha256': sha256(path),
        })
write_csv(ROOT / 'manifesto_normalizacao.csv', manifest)
(ROOT / 'manifesto_normalizacao.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')

summary = {
    'lote': 'G5-L01', 'fonte_id': 'F-013', 'versao': 'G5-L01-NORM-V1.0',
    'data_hora_utc': NOW.isoformat(), 'municipios': len(base_rows),
    'variaveis_brutas_selecionadas': len(SELECTED),
    'indicadores_derivados': len(DERIVED_META),
    'testes_aprovados': sum(1 for t in tests if t[2]), 'testes_total': len(tests),
    'divergencias_setor_municipio': len(anomalous_comparisons),
    'percentuais_fora_faixa': percent_out_of_range,
    'status': 'NORMALIZACAO_APROVADA_PARA_REVISAO' if all(t[2] for t in tests) else 'NORMALIZACAO_COM_PENDENCIAS',
    'nota_metodologica': 'A base municipal oficial é canônica. A soma setorial é usada somente como controle, pois valores X não podem ser tratados como zero.',
    'hashes_fontes': hashes,
}
(ROOT / 'resumo_execucao.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

readme = f'''# G5-L01 — Normalização do Censo 2022 complementar\n\nVersão: G5-L01-NORM-V1.0  \nData UTC: {NOW.isoformat()}\n\n## Decisão metodológica central\nA unidade-alvo do projeto é o município. Por isso, os arquivos oficiais agregados por município são usados como base canônica. Os arquivos por setor do snapshot primário foram rebaixados novamente e tiveram os hashes conferidos contra o snapshot; sua soma serve como controle independente. Valores `X` são supressões e nunca são convertidos em zero.\n\n## Escopo normalizado\n- 853 municípios de Minas Gerais;\n- 64 variáveis oficiais selecionadas;\n- 24 indicadores percentuais descritivos;\n- abastecimento e ligação à rede de água;\n- banheiro e sanitário;\n- destinação de esgoto;\n- destino do lixo;\n- contagens de domicílios e moradores.\n\n## Limites\n- não certifica adequação jurídica ou conformidade;\n- não equipara rede geral ou pluvial a tratamento adequado;\n- não imputa valores ausentes;\n- não incorpora cruzamentos por raça, sexo ou idade nesta primeira camada;\n- não integra ainda a base mestra municipal.\n'''
(ROOT / 'README_NORMALIZACAO.md').write_text(readme, encoding='utf-8')

# Pacote final compacto: inclui sub-snapshot municipal, produtos e auditoria; exclui os dois ZIPs setoriais já preservados no snapshot primário.
package = Path('mg853-g5-normalize-l01') / f'MG853_G5_L01_NORMALIZACAO_V1_0_{DATE}.zip'
with zipfile.ZipFile(package, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for path in sorted(ROOT.rglob('*')):
        if not path.is_file():
            continue
        if path.name.startswith('Agregados_por_setores_'):
            continue
        z.write(path, arcname=str(path.relative_to(ROOT)))

print(json.dumps({**summary, 'package': str(package), 'package_sha256': sha256(package), 'package_size': package.stat().st_size}, ensure_ascii=False, indent=2))
if not all(t[2] for t in tests):
    raise SystemExit(2)
