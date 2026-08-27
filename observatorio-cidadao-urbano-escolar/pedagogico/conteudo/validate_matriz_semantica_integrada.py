from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OCUE = ROOT / "observatorio-cidadao-urbano-escolar"
CONTENT = OCUE / "pedagogico" / "conteudo"
CAT = OCUE / "catalogos"
MATRIX = CONTENT / "matriz_semantica_ods_temas_direitos_ciclo_v1_0.csv"
REPORT = CONTENT / "matriz_semantica_integrada_validation_report.json"

errors: list[str] = []


def load_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def split_codes(value: str):
    return {x.strip() for x in (value or "").split(";") if x.strip()}


rows = load_csv(MATRIX)
themes = load_csv(CAT / "catalogo_temas_urbanos_v1_0.csv")
dd = load_csv(CAT / "catalogo_direitos_deveres_v1_0.csv")
ods = load_csv(CAT / "catalogo_ods_v1_0.csv")
cycle = load_csv(CAT / "catalogo_ciclo_cidadania_urbana_v1_0.csv")

valid_themes = {r["tema_codigo"] for r in themes}
valid_dd = {r["direito_dever_codigo"] for r in dd}
valid_ods = {int(r["ods_numero"]) for r in ods}
valid_cycle = {r["etapa_codigo"] for r in cycle}
valid_levels = {"N1", "N2", "N3"}
valid_axes = {f"E{i}" for i in range(1, 9)}
valid_strength = {"FORTE", "COMPLEMENTAR", "INTEGRADORA"}

required = [
    "relacao_id", "niveis_aplicaveis", "eixo_codigo", "tema_ocue_codigo",
    "direito_dever_codigo", "ods_numero", "etapa_ciclo", "forca_relacao",
    "justificativa", "fonte_origem", "status"
]
if not rows:
    errors.append("matrix_empty")
elif set(required) - set(rows[0]):
    errors.append(f"missing_columns={sorted(set(required)-set(rows[0]))}")

ids = set()
used_themes, used_dd, used_cycle, used_axes, used_levels, used_ods = set(), set(), set(), set(), set(), set()
semantic_keys = set()
for r in rows:
    rid = (r.get("relacao_id") or "").strip()
    if not rid:
        errors.append("missing_relacao_id")
    elif rid in ids:
        errors.append(f"duplicate_relacao_id={rid}")
    ids.add(rid)

    for field in required:
        if not (r.get(field) or "").strip():
            errors.append(f"{rid}:missing_{field}")

    levels = split_codes(r.get("niveis_aplicaveis", ""))
    if not levels or levels - valid_levels:
        errors.append(f"{rid}:invalid_levels={sorted(levels-valid_levels)}")
    used_levels |= levels

    axis = r.get("eixo_codigo", "")
    theme = r.get("tema_ocue_codigo", "")
    right = r.get("direito_dever_codigo", "")
    stage = r.get("etapa_ciclo", "")
    strength = r.get("forca_relacao", "")
    if axis not in valid_axes:
        errors.append(f"{rid}:invalid_axis={axis}")
    if theme not in valid_themes:
        errors.append(f"{rid}:invalid_theme={theme}")
    if right not in valid_dd:
        errors.append(f"{rid}:invalid_dd={right}")
    if stage not in valid_cycle:
        errors.append(f"{rid}:invalid_cycle={stage}")
    if strength not in valid_strength:
        errors.append(f"{rid}:invalid_strength={strength}")
    try:
        ods_num = int(r.get("ods_numero", ""))
    except ValueError:
        errors.append(f"{rid}:invalid_ods")
        ods_num = -1
    if ods_num not in valid_ods:
        errors.append(f"{rid}:ods_not_in_catalog={ods_num}")

    key = (axis, theme, right, ods_num, stage)
    if key in semantic_keys:
        errors.append(f"{rid}:duplicate_semantic_key={key}")
    semantic_keys.add(key)

    if len((r.get("justificativa") or "").strip()) < 20:
        errors.append(f"{rid}:justification_too_short")
    if r.get("status") != "VERIFICADO_ESTRUTURAL":
        errors.append(f"{rid}:invalid_status={r.get('status')}")

    used_axes.add(axis); used_themes.add(theme); used_dd.add(right); used_cycle.add(stage); used_ods.add(ods_num)

if used_axes != valid_axes:
    errors.append(f"axis_coverage_missing={sorted(valid_axes-used_axes)}")
if used_themes != valid_themes:
    errors.append(f"theme_coverage_missing={sorted(valid_themes-used_themes)}")
if used_dd != valid_dd:
    errors.append(f"rights_duties_coverage_missing={sorted(valid_dd-used_dd)}")
if used_cycle != valid_cycle:
    errors.append(f"cycle_coverage_missing={sorted(valid_cycle-used_cycle)}")
if used_levels != valid_levels:
    errors.append(f"level_coverage_missing={sorted(valid_levels-used_levels)}")

# ODS 2 e 14 nao sao forçados: o gate evita criar vínculo apenas para completar cardinalidade.
if 11 not in used_ods:
    errors.append("ods11_required_anchor_missing")

report = {
    "validator": "validate_matriz_semantica_integrada.py",
    "status": "REPROVADO" if errors else "APROVADO",
    "checks": {
        "rows": len(rows),
        "axes_covered": len(used_axes),
        "themes_covered": len(used_themes),
        "rights_duties_covered": len(used_dd),
        "cycle_stages_covered": len(used_cycle),
        "levels_covered": sorted(used_levels),
        "ods_referenced": sorted(x for x in used_ods if x > 0),
        "anti_cartesian_rule": "relacoes_curadas; cobertura ODS nao e forçada"
    },
    "errors": errors,
}
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
if errors:
    raise SystemExit(1)
