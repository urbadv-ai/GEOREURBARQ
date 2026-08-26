from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path('mg853-p1-id')
DATA = ROOT / 'data'
RAW = DATA / 'raw' / 'current'
NORM = DATA / 'normalized'
MG = DATA / 'mg853'
META = DATA / 'metadata'
HIST = DATA / 'history'
for directory in (RAW, NORM, MG, META, HIST):
    directory.mkdir(parents=True, exist_ok=True)

NOW = datetime.now(timezone.utc)
TS = NOW.replace(microsecond=0).isoformat().replace('+00:00', 'Z')
DAY = NOW.date().isoformat()
VERSION = '1.1.0'
CFG = json.loads((ROOT / 'config' / 'idsc_pipeline_config_v1_0.json').read_text(encoding='utf-8'))
BASE = CFG['fontes']['idsc_api_base']
IBGE_URL = CFG['fontes']['ibge_municipios_url']
CITY_ENDPOINTS = CFG['endpoints']['municipios_nacionais']
AUX_ENDPOINTS = CFG['endpoints']['auxiliares_nacionais']
Q = CFG['controles_qualidade']


def norm(value: Any) -> str:
    text = '' if value is None else str(value)
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', ' ', text).strip()


def safe_col(value: Any) -> str:
    return norm(value).replace(' ', '_') or 'campo'


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def new_session() -> requests.Session:
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
        backoff_factor=1.2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(['GET']),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.mount('https://', HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=16))
    session.headers.update({
        'User-Agent': 'GEOREURBARQ-IDSC/1.1 public-data-research',
        'Referer': 'https://idsc.cidadessustentaveis.org.br/',
        'Origin': 'https://idsc.cidadessustentaveis.org.br',
        'Accept': 'application/json,text/plain,*/*',
    })
    return session


SESSION = new_session()


def get_json(url: str, timeout: int = 180) -> tuple[Any, bytes, str]:
    response = SESSION.get(url, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    return response.json(), response.content, response.url


def flatten_dict(obj: Any, prefix: str = '') -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f'{prefix}.{key}' if prefix else str(key)
            if isinstance(value, dict):
                out.update(flatten_dict(value, path))
            elif isinstance(value, list):
                out[path] = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
            else:
                out[path] = value
    return out


def lists_of_dicts(obj: Any, path: str = 'root') -> list[tuple[str, list[dict[str, Any]]]]:
    found: list[tuple[str, list[dict[str, Any]]]] = []
    if isinstance(obj, list):
        if obj and all(isinstance(item, dict) for item in obj[: min(5, len(obj))]):
            found.append((path, obj))
        for index, value in enumerate(obj[:20]):
            if isinstance(value, (list, dict)):
                found.extend(lists_of_dicts(value, f'{path}[{index}]'))
    elif isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, (list, dict)):
                found.extend(lists_of_dicts(value, f'{path}.{key}'))
    return found


def scalar_leaves(obj: Any, path: str = 'root'):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from scalar_leaves(value, f'{path}.{key}')
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from scalar_leaves(value, f'{path}[{index}]')
    else:
        yield path, obj


def pick_named_column(columns: list[str], patterns: list[str], exact: tuple[str, ...] = ()) -> str | None:
    normalized = {column: norm(column) for column in columns}
    exact_norm = {norm(value) for value in exact}
    for column, name in normalized.items():
        if name in exact_norm:
            return column
    for pattern in patterns:
        for column, name in normalized.items():
            if re.search(pattern, name):
                return column
    return None


def detect_ibge_code_column(frame: pd.DataFrame, ibge_codes: set[str]) -> tuple[str | None, int]:
    """Detecta código IBGE pelo conteúdo e valida os valores contra o IBGE.

    No endpoint atual do IDSC-BR, `id` corresponde ao código IBGE de 7 dígitos.
    A detecção por conteúdo evita dependência dessa convenção nominal.
    """
    best_column = None
    best_matches = 0
    for column in frame.columns:
        values = frame[column].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
        codes = values.str.extract(r'(?<!\d)(\d{7})(?!\d)', expand=False)
        matches = int(codes.isin(ibge_codes).sum())
        if matches > best_matches:
            best_column, best_matches = column, matches
    minimum = max(100, int(len(frame) * 0.90))
    return (best_column, best_matches) if best_matches >= minimum else (None, best_matches)


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding='utf-8-sig')


def save_raw(name: str, content: bytes, url: str, manifest: list[dict[str, Any]]) -> None:
    path = RAW / name
    path.write_bytes(content)
    manifest.append({
        'arquivo': str(path.relative_to(DATA)),
        'fonte_url': url,
        'sha256': sha256_bytes(content),
        'bytes': len(content),
        'capturado_em_utc': TS,
    })


def load_ibge_crosswalk(manifest: list[dict[str, Any]]) -> pd.DataFrame:
    obj, content, final_url = get_json(IBGE_URL)
    save_raw('ibge_sidra_4714_municipios_2022.json', content, final_url, manifest)
    frame = pd.DataFrame(obj[1:])
    if not {'D1C', 'D1N'} <= set(frame.columns):
        raise RuntimeError('IBGE SIDRA sem as colunas territoriais D1C/D1N')
    crosswalk = frame[['D1C', 'D1N']].drop_duplicates().copy()
    crosswalk['cod_ibge_7'] = crosswalk['D1C'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
    parsed = crosswalk['D1N'].astype(str).str.extract(r'^(.*?)(?:\s+-\s+([A-Z]{2}))?$')
    crosswalk['municipio_ibge'] = parsed[0].str.strip()
    crosswalk['uf'] = parsed[1].fillna('')
    crosswalk['nome_norm'] = crosswalk['municipio_ibge'].map(norm)
    crosswalk = crosswalk[['cod_ibge_7', 'municipio_ibge', 'uf', 'nome_norm']].drop_duplicates('cod_ibge_7')
    if crosswalk['cod_ibge_7'].nunique() != int(Q.get('ibge_nacional_exato', 5570)):
        raise RuntimeError(f"Dimensão IBGE inesperada: {crosswalk['cod_ibge_7'].nunique()} municípios")
    write_csv(crosswalk.drop(columns='nome_norm'), META / 'ibge_municipios_crosswalk.csv')
    return crosswalk


def canonicalize_city_records(records: list[dict[str, Any]], endpoint: str, ibge: pd.DataFrame):
    source = pd.DataFrame([flatten_dict(record) for record in records])
    columns = list(source.columns)
    ibge_codes = set(ibge['cod_ibge_7'].astype(str))

    named_code = pick_named_column(columns, [r'(cod|codigo).*ibge', r'ibge.*(cod|codigo)'], ('cod_ibge_7', 'codigo_ibge'))
    content_code, content_matches = detect_ibge_code_column(source, ibge_codes)
    code_column = content_code or named_code
    if not code_column:
        raise RuntimeError(f'Não foi possível detectar coluna de código IBGE; melhor cobertura={content_matches}/{len(source)}')

    name_column = pick_named_column(columns, [r'nome.*(cidade|municipio)', r'(cidade|municipio).*nome'], ('municipio', 'cidade', 'nome'))
    uf_column = pick_named_column(columns, [r'(^| )uf($| )', r'sigla.*(uf|estado)'], ('uf', 'sigla_uf', 'siglaEstado'))
    id_column = pick_named_column(columns, [r'id.*(perfil|cidade|municipio)', r'(perfil|cidade|municipio).*id'], ('id', 'id_cidade', 'cidade_id', 'id_perfil_cidade'))
    score_column = pick_named_column(columns, [r'pontuacao.*(geral|idsc)', r'score.*(geral|idsc)'], ('pontuacao', 'score'))
    rank_column = pick_named_column(columns, [r'classificacao.*geral', r'ranking.*geral', r'posicao.*geral'], ('classificacao', 'ranking', 'posicao'))
    level_column = pick_named_column(columns, [r'nivel.*desenvolvimento', r'desenvolvimento.*nivel'], ('nivel',))

    work = source.copy()
    work['cod_ibge_7'] = work[code_column].astype(str).str.replace(r'\.0$', '', regex=True).str.extract(r'(?<!\d)(\d{7})(?!\d)', expand=False)
    if name_column:
        raw_name = work[name_column].astype(str).str.strip()
        work['nome_idsc'] = raw_name.str.replace(r'\s*[\(\-\/]\s*[A-Z]{2}\s*\)?\s*$', '', regex=True).str.strip()
        work['nome_norm'] = work['nome_idsc'].map(norm)
        work['uf_idsc'] = work[uf_column].astype(str).str.upper().str.strip() if uf_column else raw_name.str.extract(r'(?:\(|-|/)\s*([A-Z]{2})\s*\)?\s*$', expand=False).fillna('')
    else:
        work['nome_idsc'] = ''
        work['nome_norm'] = ''
        work['uf_idsc'] = work[uf_column].astype(str).str.upper().str.strip() if uf_column else ''

    reference = ibge.rename(columns={'municipio_ibge': 'municipio_ref', 'uf': 'uf_ref'})
    work = work.merge(reference[['cod_ibge_7', 'municipio_ref', 'uf_ref']], on='cod_ibge_7', how='left')
    work['municipio_ibge'] = work['municipio_ref']
    work['uf'] = work['uf_ref']
    work['status_vinculo_ibge'] = work['municipio_ref'].notna().map({True: 'CODIGO_IBGE', False: 'PENDENTE'})

    name_map = ibge[['cod_ibge_7', 'municipio_ibge', 'uf', 'nome_norm']]
    for index in work.index[work['status_vinculo_ibge'].eq('PENDENTE') & work['nome_norm'].ne('')]:
        candidates = name_map[name_map['nome_norm'].eq(work.at[index, 'nome_norm'])]
        source_uf = str(work.at[index, 'uf_idsc'] or '').upper()
        narrowed = candidates[candidates['uf'].eq(source_uf)] if source_uf else candidates
        if len(narrowed) == 1:
            row = narrowed.iloc[0]
            work.loc[index, ['cod_ibge_7', 'municipio_ibge', 'uf', 'status_vinculo_ibge']] = [
                row['cod_ibge_7'], row['municipio_ibge'], row['uf'], 'NOME_UF' if source_uf else 'NOME_UNICO'
            ]
        elif len(candidates) > 1:
            work.at[index, 'status_vinculo_ibge'] = 'AMBIGUO'
        else:
            work.at[index, 'status_vinculo_ibge'] = 'SEM_MATCH'

    ids = work[id_column].astype(str).str.replace(r'\.0$', '', regex=True).str.strip() if id_column else work['cod_ibge_7'].astype(str)
    ids = ids.replace({'': pd.NA, 'nan': pd.NA, 'None': pd.NA, '<NA>': pd.NA})

    canonical = pd.DataFrame({
        'cod_ibge_7': work['cod_ibge_7'],
        'municipio_ibge': work['municipio_ibge'],
        'uf': work['uf'],
        'id_cidade_idsc': ids,
        'pontuacao_geral_idsc': pd.to_numeric(work[score_column], errors='coerce') if score_column else pd.NA,
        'classificacao_geral_idsc': pd.to_numeric(work[rank_column], errors='coerce') if rank_column else pd.NA,
        'nivel_desenvolvimento_idsc': work[level_column] if level_column else pd.NA,
        'status_vinculo_ibge': work['status_vinculo_ibge'],
        'sistema_origem': 'IDSC-BR',
        'endpoint_origem': endpoint,
        'fonte': 'Instituto Cidades Sustentáveis / IDSC-BR',
        'url_fonte': BASE + endpoint,
        'data_extracao_utc': TS,
    })
    canonical['hash_registro_origem'] = [
        sha256_bytes(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str).encode())
        for record in records
    ]

    renamed = {column: f'src__{safe_col(column)}' for column in source.columns}
    source_wide = work.rename(columns=renamed)
    front = ['cod_ibge_7', 'municipio_ibge', 'uf', 'status_vinculo_ibge', 'nome_idsc', 'uf_idsc']
    source_wide = source_wide[front + [renamed[column] for column in source.columns if renamed[column] in source_wide.columns]]
    source_wide.insert(0, 'endpoint_origem', endpoint)
    source_wide.insert(0, 'data_extracao_utc', TS)

    diagnostics = {
        'code_column_detected': code_column,
        'code_column_matches_ibge': content_matches,
        'name_column_detected': name_column,
        'uf_column_detected': uf_column,
        'id_column_detected': id_column,
        'score_column_detected': score_column,
        'rank_column_detected': rank_column,
    }
    return canonical.drop_duplicates(['cod_ibge_7', 'id_cidade_idsc', 'hash_registro_origem']), source_wide, diagnostics


def national_ods_long(records: list[dict[str, Any]], canonical: pd.DataFrame) -> pd.DataFrame:
    by_hash = canonical.set_index('hash_registro_origem').to_dict('index')
    rows: list[dict[str, Any]] = []
    for record in records:
        record_hash = sha256_bytes(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str).encode())
        city = by_hash.get(record_hash, {})
        ods_list = None
        for key, value in record.items():
            if norm(key) in {'odslist', 'ods list', 'lista ods'} and isinstance(value, list):
                ods_list = value
                break
        if ods_list is None and isinstance(record.get('odsList'), list):
            ods_list = record['odsList']
        for ods in ods_list or []:
            if not isinstance(ods, dict):
                continue
            rows.append({
                'cod_ibge_7': city.get('cod_ibge_7'),
                'municipio_ibge': city.get('municipio_ibge'),
                'uf': city.get('uf'),
                'id_cidade_idsc': city.get('id_cidade_idsc'),
                'ods_numero': pd.to_numeric(ods.get('numOds'), errors='coerce'),
                'ods_label': ods.get('label'),
                'pontuacao_ods': pd.to_numeric(ods.get('pontuacao'), errors='coerce'),
                'rating_color': ods.get('ratingColor'),
                'tipo_origem': ods.get('type'),
                'fonte': 'Instituto Cidades Sustentáveis / IDSC-BR',
                'endpoint_origem': 'buscarAllPerfilCidadeDetalhes',
                'url_fonte': BASE + 'buscarAllPerfilCidadeDetalhes',
                'data_extracao_utc': TS,
                'hash_registro_origem': record_hash,
                'payload_ods_json': json.dumps(ods, ensure_ascii=False, separators=(',', ':')),
            })
    return pd.DataFrame(rows)


def fetch_detail(job: tuple[str, str, str]):
    code, city_id, template = job
    url = BASE + template.format(city_id=city_id)
    session = new_session()
    try:
        response = session.get(url, timeout=120)
        response.raise_for_status()
        return code, city_id, url, response.json(), None
    except Exception as exc:
        return code, city_id, url, None, repr(exc)
    finally:
        session.close()


def payload_to_long(results, names: dict[str, str]):
    rows, errors = [], []
    for code, city_id, url, obj, error in results:
        if error:
            errors.append({'cod_ibge_7': code, 'id_cidade_idsc': city_id, 'url_fonte': url, 'erro': error})
            continue
        payload_hash = sha256_bytes(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode())
        for path, value in scalar_leaves(obj):
            rows.append({
                'cod_ibge_7': code,
                'municipio_ibge': names.get(code, ''),
                'uf': 'MG',
                'id_cidade_idsc': city_id,
                'json_path': path,
                'valor': value,
                'hash_payload_origem': payload_hash,
                'url_fonte': url,
                'data_extracao_utc': TS,
            })
    return pd.DataFrame(rows), pd.DataFrame(errors)


def main() -> None:
    raw_manifest: list[dict[str, Any]] = []
    source_inventory: list[dict[str, Any]] = []
    ibge = load_ibge_crosswalk(raw_manifest)
    payloads: dict[str, Any] = {}

    for endpoint in list(dict.fromkeys(CITY_ENDPOINTS + AUX_ENDPOINTS)):
        try:
            obj, content, final_url = get_json(BASE + endpoint)
            payloads[endpoint] = obj
            save_raw(f'idsc_{endpoint}.json', content, final_url, raw_manifest)
            lists = lists_of_dicts(obj)
            source_inventory.append({
                'endpoint': endpoint,
                'status': 'OK',
                'url': final_url,
                'bytes': len(content),
                'listas_detectadas': len(lists),
                'maior_lista': max((len(values) for _, values in lists), default=0),
            })
        except Exception as exc:
            source_inventory.append({'endpoint': endpoint, 'status': 'ERRO', 'url': BASE + endpoint, 'erro': repr(exc)})

    candidates = []
    for priority, endpoint in enumerate(CITY_ENDPOINTS):
        for _, records in lists_of_dicts(payloads.get(endpoint, {})):
            candidates.append((len(records), -priority, endpoint, records))
    if not candidates:
        raise RuntimeError('IDSC sem lista municipal detectável')

    _, _, selected_endpoint, records = max(candidates, key=lambda item: (item[0], item[1]))
    national, source_wide, detection = canonicalize_city_records(records, selected_endpoint, ibge)
    national = national.sort_values(['cod_ibge_7', 'id_cidade_idsc'], na_position='last')
    write_csv(national, NORM / 'idsc_brasil_municipios.csv')
    write_csv(source_wide, NORM / 'idsc_brasil_municipios_source_wide.csv')

    ods_national = national_ods_long(records, national)
    if not ods_national.empty:
        ods_national = ods_national.sort_values(['cod_ibge_7', 'ods_numero'])
        write_csv(ods_national, NORM / 'idsc_brasil_ods_long.csv')

    for endpoint in AUX_ENDPOINTS:
        lists = lists_of_dicts(payloads.get(endpoint, {}))
        if lists:
            list_path, aux_records = max(lists, key=lambda item: len(item[1]))
            frame = pd.DataFrame([flatten_dict(record) for record in aux_records])
            frame.columns = [f'src__{safe_col(column)}' for column in frame.columns]
            frame.insert(0, 'json_path_lista', list_path)
            frame.insert(0, 'endpoint_origem', endpoint)
            frame.insert(0, 'data_extracao_utc', TS)
            write_csv(frame, NORM / f'idsc_brasil_{safe_col(endpoint)}.csv')

    ibge_mg = ibge[ibge['cod_ibge_7'].str.startswith('31')].copy().sort_values('cod_ibge_7')
    unique_national = national.dropna(subset=['cod_ibge_7']).drop_duplicates('cod_ibge_7')
    mg = ibge_mg[['cod_ibge_7', 'municipio_ibge', 'uf']].merge(
        unique_national.drop(columns=['municipio_ibge', 'uf'], errors='ignore'), on='cod_ibge_7', how='left'
    )
    mg['status_cobertura_idsc'] = mg['id_cidade_idsc'].notna().map({True: 'OK', False: 'SEM_IDSC'})
    write_csv(mg, MG / 'mg_853_idsc_municipios.csv')

    mg_ods_summary = ods_national[ods_national['cod_ibge_7'].astype(str).str.startswith('31')].copy() if not ods_national.empty else pd.DataFrame()
    if not mg_ods_summary.empty:
        write_csv(mg_ods_summary, MG / 'mg_853_idsc_ods_resumo_long.csv')

    matched = mg.dropna(subset=['id_cidade_idsc'])
    ods_template = CFG['endpoints']['detalhe_mg_ods']
    series_template = CFG['endpoints']['detalhe_mg_series']
    jobs = []
    for row in matched.itertuples(index=False):
        city_id = str(row.id_cidade_idsc).replace('.0', '')
        jobs.extend([
            (str(row.cod_ibge_7), city_id, ods_template),
            (str(row.cod_ibge_7), city_id, series_template),
        ])

    results = []
    workers = max(1, min(int(os.getenv('IDSC_MAX_WORKERS', CFG['concorrencia']['max_workers'])), 12))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(fetch_detail, job) for job in jobs]
        for future in as_completed(futures):
            results.append(future.result())

    names = ibge_mg.set_index('cod_ibge_7')['municipio_ibge'].to_dict()
    ods_marker = ods_template.split('/{')[0]
    series_marker = series_template.split('/{')[0]
    ods_long, ods_errors = payload_to_long([result for result in results if ods_marker in result[2]], names)
    series_long, series_errors = payload_to_long([result for result in results if series_marker in result[2]], names)
    if not ods_long.empty:
        write_csv(ods_long.sort_values(['cod_ibge_7', 'json_path']), MG / 'mg_853_idsc_ods_long.csv')
    if not series_long.empty:
        write_csv(series_long.sort_values(['cod_ibge_7', 'json_path']), MG / 'mg_853_idsc_series_long.csv')

    errors = pd.concat([
        ods_errors.assign(tipo='ODS'),
        series_errors.assign(tipo='SERIE'),
    ], ignore_index=True) if not ods_errors.empty or not series_errors.empty else pd.DataFrame()
    if not errors.empty:
        write_csv(errors, META / 'mg_853_idsc_detail_errors.csv')
    elif (META / 'mg_853_idsc_detail_errors.csv').exists():
        (META / 'mg_853_idsc_detail_errors.csv').unlink()

    ods_counts = ods_national.groupby('cod_ibge_7')['ods_numero'].nunique() if not ods_national.empty else pd.Series(dtype=int)
    mg_ods_counts = mg_ods_summary.groupby('cod_ibge_7')['ods_numero'].nunique() if not mg_ods_summary.empty else pd.Series(dtype=int)
    expected_national = int(Q.get('idsc_nacional_exato', 5570))
    expected_mg = int(Q.get('mg_idsc_exato', 853))
    expected_ods = int(Q.get('ods_por_municipio_esperado', 17))

    checks = {
        'pipeline_version': VERSION,
        'gerado_em_utc': TS,
        'snapshot_date': DAY,
        'endpoint_municipal_selecionado': selected_endpoint,
        'deteccao_colunas': detection,
        'registros_municipais_fonte': len(records),
        'municipios_nacionais_com_codigo_ibge_unico': int(national['cod_ibge_7'].dropna().nunique()),
        'registros_nacionais_sem_codigo_ibge': int(national['cod_ibge_7'].isna().sum()),
        'municipios_ibge_total': int(ibge['cod_ibge_7'].nunique()),
        'municipios_nacionais_com_17_ods': int((ods_counts == expected_ods).sum()),
        'linhas_ods_nacional': int(len(ods_national)),
        'municipios_mg_ibge': int(ibge_mg['cod_ibge_7'].nunique()),
        'municipios_mg_com_idsc': int(mg['id_cidade_idsc'].notna().sum()),
        'municipios_mg_sem_idsc': int(mg['id_cidade_idsc'].isna().sum()),
        'municipios_mg_com_17_ods_resumo': int((mg_ods_counts == expected_ods).sum()),
        'cobertura_ods_detalhada_mg': int(ods_long['cod_ibge_7'].nunique()) if not ods_long.empty else 0,
        'cobertura_series_mg': int(series_long['cod_ibge_7'].nunique()) if not series_long.empty else 0,
        'erros_detalhamento_mg': int(len(errors)),
        'criterios_aprovacao': Q,
    }
    checks['status_qualidade'] = 'APROVADO' if all([
        checks['municipios_ibge_total'] == expected_national,
        checks['registros_municipais_fonte'] == expected_national,
        checks['municipios_nacionais_com_codigo_ibge_unico'] == expected_national,
        checks['registros_nacionais_sem_codigo_ibge'] == 0,
        checks['municipios_nacionais_com_17_ods'] == expected_national,
        checks['municipios_mg_ibge'] == expected_mg,
        checks['municipios_mg_com_idsc'] == expected_mg,
        checks['municipios_mg_sem_idsc'] == 0,
        checks['municipios_mg_com_17_ods_resumo'] == expected_mg,
        checks['cobertura_ods_detalhada_mg'] == int(Q.get('mg_ods_detalhe_exato', expected_mg)),
        checks['cobertura_series_mg'] == int(Q.get('mg_series_exato', expected_mg)),
        checks['erros_detalhamento_mg'] <= int(Q.get('erros_detalhamento_maximo', 0)),
    ]) else 'REPROVADO'

    (META / 'idsc_quality_checks.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
    write_csv(pd.DataFrame(source_inventory), META / 'idsc_source_inventory.csv')
    (META / 'raw_manifest.json').write_text(json.dumps(raw_manifest, ensure_ascii=False, indent=2), encoding='utf-8')

    if checks['status_qualidade'] != 'APROVADO':
        raise RuntimeError('Carga IDSC reprovada: ' + json.dumps(checks, ensure_ascii=False))

    files = [
        {'arquivo': str(path.relative_to(DATA)), 'sha256': sha256_file(path), 'bytes': path.stat().st_size}
        for path in sorted(DATA.rglob('*'))
        if path.is_file() and 'history' not in path.parts and path.name != 'dataset_manifest.json'
    ]
    dataset_manifest = {
        'pipeline_version': VERSION,
        'gerado_em_utc': TS,
        'snapshot_date': DAY,
        'status_qualidade': 'APROVADO',
        'chave_territorial_canonica': 'cod_ibge_7',
        'fonte_principal': 'IDSC-BR / Instituto Cidades Sustentáveis',
        'arquivos': files,
    }
    (META / 'dataset_manifest.json').write_text(json.dumps(dataset_manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    snapshot_dir = HIST / DAY
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / 'manifest_snapshot.json').write_text(json.dumps(dataset_manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (snapshot_dir / 'quality_snapshot.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(checks, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
