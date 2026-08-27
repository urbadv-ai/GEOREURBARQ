from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OCUE = ROOT / "observatorio-cidadao-urbano-escolar"
CONTENT = OCUE / "pedagogico" / "conteudo"
BLUEPRINT = CONTENT / "blueprint_didatico_niveis_unidades_v1_0.csv"
ADAPTER = CONTENT / "adaptadores" / "adaptador_crmg_2026_habilidades_v1_0.csv"
REPORT = CONTENT / "blueprint_didatico_validation_report.json"


def load_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def split_ids(value: str):
    return [x.strip() for x in (value or "").split(";") if x.strip()]

rows = load_csv(BLUEPRINT)
adapter = load_csv(ADAPTER)
errors: list[str] = []
warnings: list[str] = []

valid_levels = {"N1", "N2", "N3"}
valid_units = {"U1", "U2", "U3", "U4"}
expected = {f"BP-{n}-{u}" for n in valid_levels for u in valid_units}
adapter_ids = {r.get("mapping_id", "") for r in adapter}
expected_hours = {"N1": 12, "N2": 16, "N3": 20}
required = [
    "blueprint_id","nivel","unidade_id","carga_horas","encontros_referencia",
    "pergunta_essencial","alvos_aprendizagem","conceitos_semanticos",
    "pre_requisitos_conceituais","escala_territorial","evidencias_entrada",
    "atividade_nucleo","produto_aprendizagem","evidencia_avaliacao",
    "vinculo_ocue","mappings_crmg_2026","status_curricular"
]
allowed_status = {"VERIFICADO_CRMG_2026", "VERIFICADO_COM_SUPORTE_TRANSVERSAL", "PARCIAL_CRMG_3T_PENDENTE"}

ids = [r.get("blueprint_id", "") for r in rows]
if len(rows) != 12 or set(ids) != expected:
    errors.append(f"blueprint_expected_12_exact_found={len(rows)} missing={sorted(expected-set(ids))} extra={sorted(set(ids)-expected)}")
if len(ids) != len(set(ids)):
    errors.append("duplicate_blueprint_id")

hours_by_level = {n: 0 for n in valid_levels}
for r in rows:
    bid = r.get("blueprint_id", "UNKNOWN")
    for f in required:
        if not (r.get(f) or "").strip():
            errors.append(f"{bid}:missing_{f}")
    n = r.get("nivel")
    u = r.get("unidade_id")
    if n not in valid_levels or u not in valid_units:
        errors.append(f"{bid}:invalid_level_or_unit={n}/{u}")
    if bid != f"BP-{n}-{u}":
        errors.append(f"{bid}:id_level_unit_mismatch")
    try:
        h = int(r.get("carga_horas", "0"))
        meetings = int(r.get("encontros_referencia", "0"))
        if h <= 0 or meetings <= 0:
            errors.append(f"{bid}:nonpositive_hours_or_meetings")
        if n in hours_by_level:
            hours_by_level[n] += h
    except ValueError:
        errors.append(f"{bid}:invalid_numeric_hours_or_meetings")
    status = r.get("status_curricular")
    if status not in allowed_status:
        errors.append(f"{bid}:invalid_status={status}")
    if n == "N1" and status != "PARCIAL_CRMG_3T_PENDENTE":
        errors.append(f"{bid}:N1_must_preserve_documented_3T_pending_status")
    if n in {"N2", "N3"} and status == "PARCIAL_CRMG_3T_PENDENTE":
        errors.append(f"{bid}:unexpected_3T_pending_outside_N1")
    refs = split_ids(r.get("mappings_crmg_2026", ""))
    if not refs:
        errors.append(f"{bid}:missing_mapping_refs")
    unknown = [x for x in refs if x not in adapter_ids]
    if unknown:
        errors.append(f"{bid}:unknown_mapping_refs={unknown}")
    if not split_ids(r.get("vinculo_ocue", "")):
        errors.append(f"{bid}:missing_ocue_link")

for n, expected_total in expected_hours.items():
    if hours_by_level[n] != expected_total:
        errors.append(f"{n}:workload_expected_{expected_total}_found={hours_by_level[n]}")

report = {
    "validator": "validate_blueprint_didatico.py",
    "version": "1.0.0",
    "status": "REPROVADO" if errors else "APROVADO_COM_PENDENCIA_DOCUMENTADA_N1_3T",
    "checks": {
        "blueprints": len(rows),
        "expected_blueprints": 12,
        "hours_by_level": hours_by_level,
        "adapter_mapping_ids_available": len(adapter_ids),
        "n1_blueprints": sum(1 for r in rows if r.get("nivel") == "N1"),
        "n2_blueprints": sum(1 for r in rows if r.get("nivel") == "N2"),
        "n3_blueprints": sum(1 for r in rows if r.get("nivel") == "N3"),
    },
    "errors": errors,
    "warnings": warnings,
}
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
if errors:
    raise SystemExit(1)
