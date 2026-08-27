from __future__ import annotations

import csv
import json
from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parents[3]
OCUE = ROOT / "observatorio-cidadao-urbano-escolar"
CONTENT = OCUE / "pedagogico" / "conteudo"
CAT = OCUE / "catalogos"
REPORT = CONTENT / "semantic_validation_report.json"

errors: list[str] = []
warnings: list[str] = []


def load_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def split_codes(value: str):
    return [x.strip() for x in (value or "").split(";") if x.strip()]


ontology = json.loads((CONTENT / "ontologia_semantica_direitos_deveres_cidade_v1_0.json").read_text(encoding="utf-8"))
progression = load_csv(CONTENT / "progressao_espiral_direitos_deveres_cidade_v1_0.csv")
matrix = load_csv(CONTENT / "matriz_alinhamento_curricular_nacional_v1_0.csv")
themes = load_csv(CAT / "catalogo_temas_urbanos_v1_0.csv")
dd = load_csv(CAT / "catalogo_direitos_deveres_v1_0.csv")
cycle = load_csv(CAT / "catalogo_ciclo_cidadania_urbana_v1_0.csv")

valid_themes = {r["tema_codigo"] for r in themes}
valid_dd = {r["direito_dever_codigo"] for r in dd}
cycle_key = "etapa_codigo" if "etapa_codigo" in cycle[0] else next(iter(cycle[0]))
valid_cycle = {r[cycle_key] for r in cycle}
valid_levels = {"N1", "N2", "N3"}
valid_axes = {f"E{i}" for i in range(1, 9)}

# Ontology cardinality and connectivity.
axes = ontology.get("eixos", [])
axis_codes = [a.get("codigo") for a in axes]
if set(axis_codes) != valid_axes or len(axis_codes) != 8:
    errors.append(f"ontology_axes_expected_E1_E8_found={axis_codes}")

levels = {f.get("codigo") for f in ontology.get("faixas", [])}
if levels != valid_levels:
    errors.append(f"ontology_levels_expected_N1_N2_N3_found={sorted(levels)}")

used_themes, used_dd, used_cycle, used_ods = set(), set(), set(), set()
for axis in axes:
    code = axis.get("codigo")
    for key in ["nome", "pergunta_geradora", "conceitos_nucleares", "temas_ocue", "direitos_deveres", "etapas_ciclo"]:
        if not axis.get(key):
            errors.append(f"{code}:missing_{key}")
    t = set(axis.get("temas_ocue", []))
    d = set(axis.get("direitos_deveres", []))
    c = set(axis.get("etapas_ciclo", []))
    o = set(axis.get("ods_prioritarios", []))
    if t - valid_themes:
        errors.append(f"{code}:invalid_theme_codes={sorted(t-valid_themes)}")
    if d - valid_dd:
        errors.append(f"{code}:invalid_dd_codes={sorted(d-valid_dd)}")
    if c - valid_cycle:
        errors.append(f"{code}:invalid_cycle_codes={sorted(c-valid_cycle)}")
    if any((not isinstance(x, int) or x < 1 or x > 17) for x in o):
        errors.append(f"{code}:invalid_ods={sorted(o)}")
    used_themes |= t
    used_dd |= d
    used_cycle |= c
    used_ods |= o

if used_themes != valid_themes:
    errors.append(f"theme_coverage_missing={sorted(valid_themes-used_themes)}")
if used_dd != valid_dd:
    errors.append(f"rights_duties_coverage_missing={sorted(valid_dd-used_dd)}")
if used_cycle != valid_cycle:
    errors.append(f"cycle_coverage_missing={sorted(valid_cycle-used_cycle)}")

# Spiral progression: complete cartesian product N1-N3 x E1-E8.
expected_pairs = {(n, e) for n in valid_levels for e in valid_axes}
progress_pairs = {(r["nivel"], r["eixo_codigo"]) for r in progression}
if len(progression) != 24:
    errors.append(f"progression_rows_expected_24_found={len(progression)}")
if progress_pairs != expected_pairs:
    errors.append(f"progression_missing_pairs={sorted(expected_pairs-progress_pairs)}")
if len(progress_pairs) != len(progression):
    errors.append("progression_duplicate_level_axis")
for r in progression:
    for field in ["verbo_cognitivo_dominante", "resultado_esperado", "produto_evidencia", "etapas_ciclo_dominantes"]:
        if not r.get(field):
            errors.append(f"progression_{r['nivel']}-{r['eixo_codigo']}:missing_{field}")
    cs = set(split_codes(r["etapas_ciclo_dominantes"]))
    if cs - valid_cycle:
        errors.append(f"progression_{r['nivel']}-{r['eixo_codigo']}:invalid_cycle={sorted(cs-valid_cycle)}")

# National alignment matrix: one canonical row per semantic cell.
if len(matrix) != 24:
    errors.append(f"matrix_rows_expected_24_found={len(matrix)}")
matrix_pairs = set()
required = [
    "linha_id","artefato_id","unidade_id","objetivo_aprendizagem","competencia_geral_bncc",
    "competencia_especifica_bncc","habilidade_bncc","objeto_conhecimento_conteudo","ods_codigo",
    "tema_ocue_codigo","etapa_ciclo","atividade_estudante","evidencia_aprendizagem",
    "instrumento_avaliacao","criterio_avaliacao","justificativa_alinhamento","fonte_curricular",
    "url_fonte","data_verificacao","status_validacao"
]
for r in matrix:
    lid = r.get("linha_id", "")
    try:
        level, axis = lid.split("-", 1)
    except ValueError:
        errors.append(f"matrix_invalid_linha_id={lid}")
        continue
    matrix_pairs.add((level, axis))
    if level not in valid_levels or axis not in valid_axes:
        errors.append(f"matrix_invalid_pair={lid}")
    for field in required:
        if not (r.get(field) or "").strip():
            errors.append(f"matrix_{lid}:missing_{field}")
    ts = set(split_codes(r.get("tema_ocue_codigo", "")))
    if ts - valid_themes:
        errors.append(f"matrix_{lid}:invalid_theme={sorted(ts-valid_themes)}")
    cs = set(split_codes(r.get("etapa_ciclo", "")))
    if cs - valid_cycle:
        errors.append(f"matrix_{lid}:invalid_cycle={sorted(cs-valid_cycle)}")
    for ods in split_codes(r.get("ods_codigo", "")):
        if not ods.isdigit() or not (1 <= int(ods) <= 17):
            errors.append(f"matrix_{lid}:invalid_ods={ods}")
    if r.get("habilidade_rede_codigo") == "PENDENTE_ADAPTADOR_REDE":
        pass
    else:
        warnings.append(f"matrix_{lid}:network_adapter_field_not_pending_review")

if matrix_pairs != expected_pairs:
    errors.append(f"matrix_missing_pairs={sorted(expected_pairs-matrix_pairs)}")
if len(matrix_pairs) != len(matrix):
    errors.append("matrix_duplicate_level_axis")

# Coverage at each level and content-document guardrails.
for level in valid_levels:
    rows = [r for r in matrix if r["linha_id"].startswith(level + "-")]
    if len(rows) != 8:
        errors.append(f"{level}:matrix_expected_8_axes_found={len(rows)}")

program_text = (CONTENT / "CONTEUDO_PROGRAMATICO_DIREITOS_DEVERES_CIDADE_v1_0.md").read_text(encoding="utf-8")
for marker in ["### E1", "### E2", "### E3", "### E4", "### E5", "### E6", "### E7", "### E8", "Ciclo de Cidadania Urbana", "Nenhuma pontuação municipal do IDSC"]:
    if marker not in program_text:
        errors.append(f"program_missing_marker={marker}")

network_pending = sum(1 for r in matrix if r.get("habilidade_rede_codigo") == "PENDENTE_ADAPTADOR_REDE")
status = "REPROVADO" if errors else ("APROVADO_ESTRUTURAL_COM_PENDENCIA_ADAPTADOR_REDE" if network_pending else "APROVADO")
report = {
    "validator": "validate_conteudo_semantico.py",
    "ontology_version": ontology.get("version"),
    "status": status,
    "checks": {
        "axes": len(axis_codes),
        "levels": len(levels),
        "progression_rows": len(progression),
        "matrix_rows": len(matrix),
        "themes_catalog": len(valid_themes),
        "themes_covered": len(used_themes),
        "rights_duties_catalog": len(valid_dd),
        "rights_duties_covered": len(used_dd),
        "cycle_stages_catalog": len(valid_cycle),
        "cycle_stages_covered": len(used_cycle),
        "ods_referenced": sorted(used_ods),
        "network_adapter_pending_rows": network_pending,
    },
    "errors": errors,
    "warnings": warnings,
}
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
if errors:
    raise SystemExit(1)
