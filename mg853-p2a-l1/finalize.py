from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import shutil
import zipfile
from collections import defaultdict
from pathlib import Path

import pandas as pd
import requests

ROOT = Path('mg853-p2a-l1')
RAW = ROOT / 'output' / 'raw'
SRC = ROOT / 'output' / 'normalized'
FINAL = ROOT / 'final'
NORM = FINAL / 'normalized'
AUDIT = FINAL / 'audit'
DOC = FINAL / 'documentation'
if FINAL.exists():
    shutil.rmtree(FINAL)
for p in (NORM, AUDIT, DOC):
    p.mkdir(parents=True, exist_ok=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def ratio(a, b):
    a = pd.to_numeric(a, errors='coerce')
    b = pd.to_numeric(b, errors='coerce')
    return (a / b.where(b.ne(0))) * 100


def write_ptbr(df: pd.DataFrame, path: Path):
    df.to_csv(path, sep=';', decimal=',', index=False, encoding='utf-8-sig')

# ------------------------------------------------------------------
# Base municipal e áreas territoriais 2025
# ------------------------------------------------------------------
area_xls = RAW / 'AR_BR_RG_UF_RGINT_RGI_MUN_2025.xls'
areas_raw = pd.read_excel(area_xls, sheet_name='AR_BR_MUN_2025', engine='xlrd')
areas = pd.DataFrame({
    'cod_ibge_7': areas_raw['CD_MUN'].astype(str).str.replace(r'\.0$', '', regex=True).str.zfill(7),
    'municipio': areas_raw['NM_MUN'].astype(str),
    'uf': areas_raw['NM_UF_SIGLA'].astype(str),
    'area_oficial_km2_ref_2025': pd.to_numeric(areas_raw['AR_MUN_2025'], errors='coerce'),
})
areas = areas[areas.cod_ibge_7.str.startswith('31')].drop_duplicates('cod_ibge_7').sort_values('cod_ibge_7')
areas['fonte'] = 'IBGE — Áreas Territoriais 2025'
areas['ano_referencia'] = 2025
areas['url_fonte'] = 'https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/areas_territoriais/2025/AR_BR_RG_UF_RGINT_RGI_MUN_2025.xls'
areas['status_validacao'] = areas.area_oficial_km2_ref_2025.notna().map({True: 'OK', False: 'ERRO_AREA_NULA'})
assert len(areas) == 853 and areas.cod_ibge_7.nunique() == 853 and areas.area_oficial_km2_ref_2025.notna().sum() == 853
write_ptbr(areas, NORM / 'MG_853_AREAS_TERRITORIAIS_2025_V1_0.csv')
base = areas[['cod_ibge_7', 'municipio', 'area_oficial_km2_ref_2025']].copy()

# ------------------------------------------------------------------
# Malha Municipal 2025
# ------------------------------------------------------------------
malha = pd.read_csv(SRC / 'MG_853_MALHA_MUNICIPAL_2025_ATRIBUTOS.csv', dtype={'cod_ibge_7': str})
malha.cod_ibge_7 = malha.cod_ibge_7.str.zfill(7)
malha['crs_geometria'] = 'EPSG:4674'
malha['fonte'] = 'IBGE — Malha Municipal Digital 2025'
malha['ano_referencia'] = 2025
malha['url_fonte'] = 'https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_municipais/municipio_2025/UFs/MG/MG_Municipios_2025.zip'
malha['status_validacao'] = 'OK'
assert len(malha) == 853 and malha.cod_ibge_7.nunique() == 853
write_ptbr(malha, NORM / 'MG_853_MALHA_MUNICIPAL_2025_ATRIBUTOS_V1_0.csv')
shutil.copy2(SRC / 'MG_853_MALHA_MUNICIPAL_2025.gpkg', NORM / 'MG_853_MALHA_MUNICIPAL_2025.gpkg')

# ------------------------------------------------------------------
# Entorno urbano municipal — três ponderações
# ------------------------------------------------------------------
ent = pd.read_csv(SRC / 'MG_853_ENTORNO_URBANO_2022_MUNICIPIO_COMPLETO.csv', dtype={'cod_ibge_7': str})
ent.cod_ibge_7 = ent.cod_ibge_7.str.zfill(7)
weights = {
    'domicilios': ('mun_domicilios__', 'V050'),
    'faces': ('mun_faces__', 'V054'),
    'moradores': ('mun_moradores__', 'V052'),
}
metrics = {
    'pct_pavimentacao': (6, 7, 8),
    'pct_bueiro_boca_lobo': (9, 10, 11),
    'pct_iluminacao_publica': (12, 13, 14),
    'pct_ponto_onibus_van': (15, 16, 17),
    'pct_sinalizacao_cicloviaria': (18, 19, 20),
    'pct_calcada': (21, 22, 23),
    'pct_calcada_com_obstaculo': (24, 25, 26),
    'pct_rampa_cadeirante': (27, 28, 29),
}
out = ent[['cod_ibge_7']].merge(base[['cod_ibge_7', 'municipio']], on='cod_ibge_7', how='left', validate='one_to_one')
for weight, (prefix, varprefix) in weights.items():
    def col(i):
        return pd.to_numeric(ent[f'{prefix}{varprefix}{i:02d}'], errors='coerce')
    out[f'{weight}_universo_total'] = col(0)
    for name, (yes, no, nd) in metrics.items():
        denominator = col(yes).fillna(0) + col(no).fillna(0) + col(nd).fillna(0)
        out[f'{weight}_{name}'] = ratio(col(yes), denominator)
        out[f'{weight}_{name}_denominador'] = denominator
    arbor_den = col(30).fillna(0) + col(31).fillna(0) + col(32).fillna(0) + col(33).fillna(0)
    out[f'{weight}_pct_arborizacao_alguma'] = ratio(col(31).fillna(0) + col(32).fillna(0) + col(33).fillna(0), arbor_den)
    out[f'{weight}_pct_arborizacao_5_ou_mais'] = ratio(col(33), arbor_den)
    out[f'{weight}_arborizacao_denominador'] = arbor_den
out['fonte'] = 'IBGE — Censo 2022, Características Urbanísticas do Entorno dos Domicílios'
out['ano_referencia'] = 2022
out['url_fonte'] = 'https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios_Caracteristicas_urbanisticas_do_entorno_dos_domicilios/'
out['status_validacao'] = 'OK'
assert len(out) == 853 and out.cod_ibge_7.nunique() == 853
write_ptbr(out, NORM / 'MG_853_ENTORNO_URBANO_2022_INDICADORES_V1_0.csv')
shutil.copy2(SRC / 'MG_853_ENTORNO_URBANO_2022_MUNICIPIO_COMPLETO.csv', NORM / 'MG_853_ENTORNO_URBANO_2022_MUNICIPIO_COMPLETO_CODIFICADO.csv')

# Correção do arquivo percentual setorial de formato CSV irregular
pct_in = RAW / 'br_setores_entorno_cd2022_percentuais.csv'
pct_out = NORM / 'MG_SETORES_ENTORNO_PERCENTUAIS_2022_V1_1.csv.gz'
percent_rows = 0
percent_municipios = set()
invalid_lines = 0
with pct_in.open(encoding='utf-8-sig') as fi, gzip.open(pct_out, 'wt', encoding='utf-8-sig', newline='') as fo:
    headers = next(csv.reader([fi.readline().rstrip('\r\n')], delimiter=','))
    code_index = headers.index('cd_setor')
    writer = csv.writer(fo, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
    writer.writerow(headers + ['cod_ibge_7'])
    for line in fi:
        line = line.rstrip('\r\n')
        if line.startswith('"') and line.endswith('"'):
            line = line[1:-1].replace('""', '"')
        row = next(csv.reader([line], delimiter=',', quotechar='"'))
        if len(row) != len(headers):
            invalid_lines += 1
            continue
        sector = row[code_index].strip().strip('"')
        if sector.startswith('31'):
            writer.writerow(row + [sector[:7]])
            percent_rows += 1
            percent_municipios.add(sector[:7])
assert len(percent_municipios) == 853 and invalid_lines == 0

# ------------------------------------------------------------------
# Agregados básicos dos setores — estrutura urbano/rural
# ------------------------------------------------------------------
sector_zip = RAW / 'agg_setor_Agregados_por_setores_basico_BR_20260520.zip'
sector_out = NORM / 'MG_SETORES_CENSITARIOS_BASICO_2022_V1_0.csv.gz'
with zipfile.ZipFile(sector_zip) as z:
    member = z.namelist()[0]
    with z.open(member) as raw:
        sectors = pd.read_csv(raw, sep=';', decimal=',', encoding='latin1', low_memory=False, dtype={'CD_SETOR': str, 'CD_MUN': str})
sectors.CD_MUN = sectors.CD_MUN.astype(str).str.zfill(7)
sectors = sectors[sectors.CD_MUN.str.startswith('31')].copy()
sectors['cod_ibge_7'] = sectors.CD_MUN
sectors.to_csv(sector_out, sep=';', decimal=',', index=False, encoding='utf-8-sig', compression='gzip')
sectors['situacao_norm'] = sectors.SITUACAO.astype(str).str.lower()
sectors['urbano'] = sectors.situacao_norm.str.contains('urbana', na=False)
sectors['rural'] = sectors.situacao_norm.str.contains('rural', na=False)
for c in ['AREA_KM2', 'v0001', 'v0002', 'v0007', 'v0008', 'v0009']:
    sectors[c] = pd.to_numeric(sectors[c], errors='coerce').fillna(0)
g = sectors.groupby('cod_ibge_7', as_index=False).agg(
    quantidade_setores_total=('CD_SETOR', 'count'),
    area_setores_total_km2=('AREA_KM2', 'sum'),
    populacao_setores_total=('v0001', 'sum'),
    domicilios_total=('v0002', 'sum'),
    domicilios_particulares_ocupados=('v0007', 'sum'),
    domicilios_uso_ocasional=('v0008', 'sum'),
    domicilios_vagos=('v0009', 'sum'),
)
urban = sectors[sectors.urbano].groupby('cod_ibge_7', as_index=False).agg(quantidade_setores_urbanos=('CD_SETOR', 'count'), area_setores_urbanos_km2=('AREA_KM2', 'sum'), populacao_setores_urbanos=('v0001', 'sum'))
rural = sectors[sectors.rural].groupby('cod_ibge_7', as_index=False).agg(quantidade_setores_rurais=('CD_SETOR', 'count'), area_setores_rurais_km2=('AREA_KM2', 'sum'), populacao_setores_rurais=('v0001', 'sum'))
g = base.merge(g, on='cod_ibge_7', how='left', validate='one_to_one').merge(urban, on='cod_ibge_7', how='left').merge(rural, on='cod_ibge_7', how='left')
for c in ['quantidade_setores_urbanos', 'area_setores_urbanos_km2', 'populacao_setores_urbanos', 'quantidade_setores_rurais', 'area_setores_rurais_km2', 'populacao_setores_rurais']:
    g[c] = g[c].fillna(0)
g['pct_populacao_urbana_setorial'] = ratio(g.populacao_setores_urbanos, g.populacao_setores_total)
g['pct_populacao_rural_setorial'] = ratio(g.populacao_setores_rurais, g.populacao_setores_total)
g['densidade_populacional_area_oficial_2025'] = g.populacao_setores_total / g.area_oficial_km2_ref_2025
g['pct_area_setores_urbanos_sobre_area_oficial'] = ratio(g.area_setores_urbanos_km2, g.area_oficial_km2_ref_2025)
g['fonte'] = 'IBGE — Censo 2022, Agregados por Setores Censitários, Básico; IBGE Áreas 2025'
g['ano_referencia_dados'] = 2022
g['ano_referencia_area'] = 2025
g['url_fonte'] = 'https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/Agregados_por_Setor_csv/Agregados_por_setores_basico_BR_20260520.zip'
g['status_validacao'] = 'OK'
assert len(g) == 853 and g.quantidade_setores_total.notna().sum() == 853
write_ptbr(g, NORM / 'MG_853_ESTRUTURA_SETORES_CENSITARIOS_2022_V1_0.csv')

# Arquivos completos de domicílios — setor e município
for zip_name, out_name, code_col, sector_level in [
    ('agg_setor_Agregados_por_setores_caracteristicas_domicilio1_BR.zip', 'MG_SETORES_CENSITARIOS_DOMICILIO1_2022_V1_0.csv.gz', 'CD_setor', True),
    ('agg_municipio_Agregados_por_municipios_basico_BR_20260520.zip', 'MG_853_AGREGADOS_CENSO2022_BASICO_COMPLETO_V1_0.csv.gz', 'CD_MUN', False),
    ('agg_municipio_Agregados_por_municipios_caracteristicas_domicilio1_BR.zip', 'MG_853_AGREGADOS_CENSO2022_DOMICILIO1_COMPLETO_V1_0.csv.gz', 'CD_MUN', False),
]:
    with zipfile.ZipFile(RAW / zip_name) as z:
        with z.open(z.namelist()[0]) as raw:
            df = pd.read_csv(raw, sep=';', decimal=',', encoding='latin1', low_memory=False, dtype={code_col: str})
    codes = df[code_col].astype(str).str[:7].str.zfill(7) if sector_level else df[code_col].astype(str).str.zfill(7)
    df = df[codes.str.startswith('31')].copy()
    df['cod_ibge_7'] = codes[codes.str.startswith('31')]
    df.to_csv(NORM / out_name, sep=';', decimal=',', index=False, encoding='utf-8-sig', compression='gzip')

# ------------------------------------------------------------------
# Favelas e Comunidades Urbanas
# ------------------------------------------------------------------
fcu = pd.read_csv(SRC / 'MG_FCU_SETORES_E_ATRIBUTOS_2022.csv', dtype=str)
fcu.cod_ibge_7 = fcu.cod_ibge_7.str.zfill(7)
fcu_agg = fcu.groupby('cod_ibge_7', as_index=False).agg(
    quantidade_fcu=('CD_FCU', 'nunique'),
    quantidade_setores_fcu=('CD_SETOR', 'nunique'),
    nomes_fcu=('NM_FCU', lambda x: ' | '.join(sorted(set(x.dropna())))),
)
spatial = pd.read_csv(SRC / 'MG_853_FCU_RESUMO_ESPACIAL_2022.csv', dtype={'cod_ibge_7': str})
spatial.cod_ibge_7 = spatial.cod_ibge_7.str.zfill(7)
fcu_mg = base.merge(fcu_agg, on='cod_ibge_7', how='left').merge(spatial, on='cod_ibge_7', how='left')
for c in ['quantidade_fcu', 'quantidade_setores_fcu', 'quantidade_poligonos_fcu', 'area_fcu_km2_calc']:
    fcu_mg[c] = pd.to_numeric(fcu_mg[c], errors='coerce').fillna(0)
fcu_mg['possui_favela_comunidade_urbana'] = fcu_mg.quantidade_fcu.gt(0).map({True: 'SIM', False: 'NÃO'})
fcu_mg['pct_area_municipal_em_fcu'] = ratio(fcu_mg.area_fcu_km2_calc, fcu_mg.area_oficial_km2_ref_2025)
fcu_mg['nomes_fcu'] = fcu_mg.nomes_fcu.fillna('')
fcu_mg['fonte'] = 'IBGE — Censo 2022, Favelas e Comunidades Urbanas'
fcu_mg['ano_referencia'] = 2022
fcu_mg['url_fonte'] = 'https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Favelas_e_comunidades_urbanas_Resultados_do_universo/'
fcu_mg['status_cobertura'] = 'COBERTURA_NACIONAL_COMPLETA'
fcu_mg['status_validacao'] = 'OK'
assert len(fcu_mg) == 853 and fcu_mg.possui_favela_comunidade_urbana.eq('SIM').sum() == 59
write_ptbr(fcu_mg, NORM / 'MG_853_FAVELAS_COMUNIDADES_URBANAS_2022_V1_0.csv')
shutil.copy2(SRC / 'MG_FCU_POLIGONOS_2022.gpkg', NORM / 'MG_FCU_POLIGONOS_2022.gpkg')
shutil.copy2(SRC / 'MG_FCU_SETORES_E_ATRIBUTOS_2022.csv', NORM / 'MG_FCU_SETORES_E_ATRIBUTOS_2022.csv')

# ------------------------------------------------------------------
# Dicionários e auditoria
# ------------------------------------------------------------------
dictionary_url = 'https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/dicionario_de_dados_agregados_por_setores_censitarios_20260520.xlsx'
r = requests.get(dictionary_url, timeout=300); r.raise_for_status()
(DOC / 'dicionario_de_dados_agregados_por_setores_censitarios_20260520.xlsx').write_bytes(r.content)
for p in (RAW / 'entorno_dicionario').glob('*.xlsx'):
    shutil.copy2(p, DOC / p.name)

checks = pd.DataFrame([
    ['Áreas territoriais 2025', len(areas), areas.cod_ibge_7.nunique(), 853, 'OK', 'AR_MUN_2025 completo.'],
    ['Malha municipal 2025', len(malha), malha.cod_ibge_7.nunique(), 853, 'OK', '853 geometrias válidas na coleta.'],
    ['Entorno municipal derivado', len(out), out.cod_ibge_7.nunique(), 853, 'OK', 'Três ponderações: domicílios, faces e moradores.'],
    ['Entorno percentuais por setor', percent_rows, len(percent_municipios), 853, 'OK', f'Parser corrigido; linhas inválidas={invalid_lines}.'],
    ['Estrutura setorial municipal', len(g), g.cod_ibge_7.nunique(), 853, 'OK', 'Básico atualizado em maio de 2026.'],
    ['Favelas e Comunidades Urbanas', len(fcu_mg), int(fcu_mg.possui_favela_comunidade_urbana.eq('SIM').sum()), 59, 'OK', '59 municípios com presença oficial identificada.'],
], columns=['camada', 'registros', 'codigos_unicos_ou_municipios', 'meta', 'status', 'observacao'])
write_ptbr(checks, AUDIT / 'P2A_L1_AUDITORIA_DE_CAMADAS_V1_0.csv')

manifest = []
for p in sorted(FINAL.rglob('*')):
    if p.is_file():
        manifest.append({'arquivo': str(p.relative_to(FINAL)), 'bytes': p.stat().st_size, 'sha256': sha256(p)})
(AUDIT / 'MANIFEST_P2A_L1_V1_0.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
summary = {
    'status': 'APROVADO_PARA_INCORPORACAO_P2A_L1',
    'municipios': 853,
    'areas': len(areas),
    'malha': len(malha),
    'entorno_municipal': len(out),
    'entorno_setores_percentuais': percent_rows,
    'setores_basico_mg': len(sectors),
    'fcu_municipios_positivos': int(fcu_mg.possui_favela_comunidade_urbana.eq('SIM').sum()),
    'files': len(manifest),
}
(AUDIT / 'RESUMO_P2A_L1_V1_0.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False, indent=2))
