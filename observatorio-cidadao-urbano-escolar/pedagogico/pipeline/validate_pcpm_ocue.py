from __future__ import annotations

import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path('observatorio-cidadao-urbano-escolar')
PED = ROOT / 'pedagogico'
CONFIG = PED / 'config' / 'pcpm_ocue_config_v1_0.json'
NORM = PED / 'normas' / 'matriz_normativa_pedagogica_v1_0.json'
OCUE_META = ROOT / 'metadata' / 'bootstrap_validation_v1_0.json'
IDSC_META = Path('mg853-p1-id/data/metadata/idsc_quality_checks.json')

REQUIRED_FILES = [
    PED / 'PCPM_OCUE_PROTOCOLO_MESTRE_v1_0.md',
    PED / 'templates' / 'template_conteudo_programatico_v1_0.md',
    PED / 'templates' / 'template_matriz_alinhamento_curricular_v1_0.csv',
    PED / 'templates' / 'template_sequencia_didatica_v1_0.md',
    PED / 'templates' / 'template_protocolo_aplicacao_escolar_v1_0.md',
    PED / 'templates' / 'rubrica_validacao_pedagogica_v1_0.csv',
]

REQUIRED_NORM_IDS = {
    'FED_LDB_9394', 'CNE_DCN_GERAIS_4_2010', 'MEC_BNCC', 'CNE_EDH_1_2012',
    'FED_PNEA_9795', 'CNE_EA_2_2012', 'MEC_TCT_GUIA', 'MEC_ORIENTACOES_PP',
    'MEC_CRITERIOS_CURRICULO', 'MG_CRMG_2026', 'MG_PLANOS_CURSO',
    'LGPD_CRIANCAS', 'ECA_DIGITAL_15211_2025', 'DNE_OABMG_2025_2026',
    'ABNT_14724', 'ABNT_6023', 'ABNT_10520', 'ABNT_6024_6027_6028'
}

REQUIRED_MATRIX_COLUMNS = {
    'linha_id','artefato_id','unidade_id','objetivo_aprendizagem',
    'competencia_geral_bncc','habilidade_bncc','habilidade_rede_codigo',
    'objeto_conhecimento_conteudo','tct_macroarea','ods_codigo',
    'tema_ocue_codigo','etapa_ciclo','atividade_estudante','evidencia_aprendizagem',
    'instrumento_avaliacao','criterio_avaliacao','justificativa_alinhamento',
    'fonte_curricular','data_verificacao','status_validacao'
}

errors: list[str] = []
checks: dict[str, object] = {}

def fail(msg: str) -> None:
    errors.append(msg)

def read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception as exc:
        fail(f'JSON inválido/ausente {p}: {exc!r}')
        return {}

for p in [CONFIG, NORM, OCUE_META, IDSC_META, *REQUIRED_FILES]:
    if not p.exists():
        fail(f'Arquivo obrigatório ausente: {p}')

cfg = read_json(CONFIG) if CONFIG.exists() else {}
norm = read_json(NORM) if NORM.exists() else {}
ocue = read_json(OCUE_META) if OCUE_META.exists() else {}
idsc = read_json(IDSC_META) if IDSC_META.exists() else {}

# Dependency gates
checks['ocue_bootstrap_status'] = ocue.get('status')
checks['idsc_status'] = idsc.get('status_qualidade')
if ocue.get('status') != 'APROVADO': fail('Bootstrap OCUE não está APROVADO')
if idsc.get('status_qualidade') != 'APROVADO': fail('Dependência IDSC não está APROVADA')
if idsc.get('municipios_ibge_total') != 5570: fail('IDSC/IBGE nacional diverge de 5570')
if idsc.get('municipios_mg_com_idsc') != 853: fail('IDSC MG diverge de 853')
if idsc.get('linhas_ods_nacional') != 94690: fail('Matriz município×ODS diverge de 94690')

# Protocol contract
checks['protocol_id'] = cfg.get('protocol_id')
checks['protocol_version'] = cfg.get('version')
checks['gate_count'] = len(cfg.get('gates', []))
checks['curricular_modes'] = len(cfg.get('modos_insercao_curricular_permitidos', []))
if cfg.get('protocol_id') != 'PCPM_OCUE': fail('protocol_id inválido')
if len(cfg.get('gates', [])) != 13: fail('PCPM deve possuir exatamente G0-G12')
if {g.get('id') for g in cfg.get('gates', [])} != {f'G{i}' for i in range(13)}: fail('IDs dos gates G0-G12 inválidos')
if len(cfg.get('modos_insercao_curricular_permitidos', [])) < 7: fail('Modos de inserção curricular incompletos')
if not cfg.get('fail_closed'): fail('PCPM deve operar fail-closed')

# Normative freshness
verified = cfg.get('normative_last_verified')
max_days = int(cfg.get('normative_review_max_days', 0) or 0)
try:
    vd = datetime.strptime(verified, '%Y-%m-%d').date()
    age = (date.today() - vd).days
    checks['normative_age_days'] = age
    checks['normative_max_days'] = max_days
    if age < 0: fail('Data de verificação normativa está no futuro')
    if max_days <= 0 or age > max_days: fail(f'Revisão normativa vencida: {age} dias > {max_days}')
except Exception as exc:
    fail(f'Data de verificação normativa inválida: {exc!r}')

# Normative registry coverage
refs = norm.get('referencias', [])
ids = {r.get('id') for r in refs}
checks['normative_reference_count'] = len(refs)
missing_norms = sorted(REQUIRED_NORM_IDS - ids)
if missing_norms: fail('Referências normativas mínimas ausentes: ' + ', '.join(missing_norms))
for r in refs:
    if not r.get('autoridade') or not r.get('tipo') or not r.get('ato') or not r.get('status_aplicacao'):
        fail(f'Referência normativa incompleta: {r.get("id")}')

# Curricular alignment CSV contract
matrix = PED / 'templates' / 'template_matriz_alinhamento_curricular_v1_0.csv'
if matrix.exists():
    with matrix.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f)
        header = next(reader, [])
    missing_cols = sorted(REQUIRED_MATRIX_COLUMNS - set(header))
    checks['alignment_matrix_columns'] = len(header)
    if missing_cols: fail('Colunas obrigatórias ausentes na matriz curricular: ' + ', '.join(missing_cols))

# Rubric contract
rubric = PED / 'templates' / 'rubrica_validacao_pedagogica_v1_0.csv'
if rubric.exists():
    with rubric.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    checks['rubric_criteria_count'] = len(rows)
    critical = [r for r in rows if str(r.get('condicao_critica','')).strip().upper() == 'SIM']
    checks['rubric_critical_count'] = len(critical)
    if len(rows) < 20: fail('Rubrica deve possuir ao menos 20 critérios')
    if len(critical) < 10: fail('Rubrica possui poucos controles críticos')

# Mandatory headings in core templates
heading_contracts = {
    PED / 'templates' / 'template_conteudo_programatico_v1_0.md': ['## 7. Alinhamento curricular','## 11. Avaliação da aprendizagem','## 12. Inclusão, acessibilidade e equidade','## 13. Ética, privacidade e proteção de dados','## 15. Governança e aprovação'],
    PED / 'templates' / 'template_sequencia_didatica_v1_0.md': ['## 5. Alinhamento curricular','## 8. Avaliação','## 9. Inclusão e acessibilidade','## 10. Privacidade e segurança','## 11. Relação com o OCUE'],
    PED / 'templates' / 'template_protocolo_aplicacao_escolar_v1_0.md': ['## B. Enquadramento curricular','## C. Aprovações e pactuação','## G. Avaliação da aprendizagem','## I. Proteção de dados e ética','## J. Relatório pós-aplicação'],
}
for p, headings in heading_contracts.items():
    if p.exists():
        text = p.read_text(encoding='utf-8')
        for h in headings:
            if h not in text: fail(f'Seção obrigatória ausente em {p.name}: {h}')

report = {
    'dataset_id': 'PCPM_OCUE',
    'version': cfg.get('version'),
    'validated_at': date.today().isoformat(),
    'status': 'APROVADO' if not errors else 'REPROVADO',
    'checks': checks,
    'errors': errors,
}
out = PED / 'metadata' / 'pcpm_validation_runtime.json'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
sys.exit(1 if errors else 0)
