from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BASE = ROOT / "observatorio-cidadao-urbano-escolar" / "pedagogico" / "conteudo" / "adaptadores"
ATOMIC = BASE / "adaptador_crmg_2026_habilidades_v1_0.csv"
COVERAGE = BASE / "adaptador_crmg_2026_cobertura_v1_0.csv"
REPORT = BASE / "adaptador_crmg_2026_validation_report.json"


def load_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def split_ids(value: str):
    return [x.strip() for x in (value or "").split(";") if x.strip()]


atomic = load_csv(ATOMIC)
coverage = load_csv(COVERAGE)
errors: list[str] = []
warnings: list[str] = []

valid_levels = {"N1", "N2", "N3"}
valid_axes = {f"E{i}" for i in range(1, 9)}
expected_cells = {f"{n}-{e}" for n in valid_levels for e in valid_axes}
verified_statuses = {"VERIFICADO_PLANO_CURSO_2026"}
pending_statuses = {"AGUARDA_AUDITORIA_PLANO_3T_2026", "PARCIAL_AGUARDA_3T_2026"}
coverage_statuses = {
    "VERIFICADO_PLANO_CURSO_2026",
    "VERIFICADO_COM_SUPORTE_COMPLEMENTAR",
    "AGUARDA_AUDITORIA_PLANO_3T_2026",
    "PARCIAL_AGUARDA_3T_2026",
}
strengths = {"FORTE", "COMPLEMENTAR", "INTEGRADORA"}

# Atomic mappings.
ids = [r.get("mapping_id", "") for r in atomic]
if len(ids) != len(set(ids)):
    errors.append("duplicate_mapping_id")
if any(not x for x in ids):
    errors.append("blank_mapping_id")

mapping_by_id = {r["mapping_id"]: r for r in atomic if r.get("mapping_id")}
verified_atomic = 0
pending_atomic = 0
for r in atomic:
    mid = r.get("mapping_id", "UNKNOWN")
    for field in ["nivel", "eixo_codigo", "ano_escolar", "trimestre", "componente", "habilidade_crmg_codigo", "resumo_semantico", "forca_relacao", "fonte_documento", "data_verificacao", "status"]:
        if not (r.get(field) or "").strip():
            errors.append(f"{mid}:missing_{field}")
    if r.get("nivel") not in valid_levels:
        errors.append(f"{mid}:invalid_level={r.get('nivel')}")
    if r.get("eixo_codigo") not in valid_axes:
        errors.append(f"{mid}:invalid_axis={r.get('eixo_codigo')}")
    if r.get("forca_relacao") not in strengths:
        errors.append(f"{mid}:invalid_strength={r.get('forca_relacao')}")
    status = r.get("status")
    if status in verified_statuses:
        verified_atomic += 1
        url = (r.get("fonte_url") or "").strip()
        if not url.startswith("https://drive.google.com/"):
            errors.append(f"{mid}:verified_without_official_drive_source")
        if r.get("trimestre") not in {"1", "2", "3"}:
            errors.append(f"{mid}:verified_invalid_trimester={r.get('trimestre')}")
    elif status in pending_statuses:
        pending_atomic += 1
        if r.get("nivel") != "N1":
            warnings.append(f"{mid}:pending_outside_N1_review_scope")
    else:
        errors.append(f"{mid}:invalid_status={status}")

# Coverage must represent exactly the semantic cartesian product.
cells = [r.get("cell_id", "") for r in coverage]
if set(cells) != expected_cells or len(cells) != 24:
    errors.append(f"coverage_cells_expected_24_exact_found={len(cells)} missing={sorted(expected_cells-set(cells))} extra={sorted(set(cells)-expected_cells)}")
if len(cells) != len(set(cells)):
    errors.append("duplicate_coverage_cell")

fully_verified_cells = 0
partial_cells = 0
pending_cells = 0
for r in coverage:
    cell = r.get("cell_id", "UNKNOWN")
    status = r.get("cobertura_status")
    if status not in coverage_statuses:
        errors.append(f"{cell}:invalid_coverage_status={status}")
        continue
    expected_level, expected_axis = cell.split("-", 1) if "-" in cell else ("", "")
    if r.get("nivel") != expected_level or r.get("eixo_codigo") != expected_axis:
        errors.append(f"{cell}:level_axis_mismatch")

    verified_refs = split_ids(r.get("mappings_verificados", ""))
    pending_refs = split_ids(r.get("mappings_pendentes", ""))
    for ref in verified_refs + pending_refs:
        if ref not in mapping_by_id:
            errors.append(f"{cell}:unknown_mapping_ref={ref}")
        elif mapping_by_id[ref].get("nivel") != r.get("nivel") or mapping_by_id[ref].get("eixo_codigo") != r.get("eixo_codigo"):
            # Integrative cells can cite mappings from other axes to represent a chain.
            if r.get("eixo_codigo") != "E8":
                errors.append(f"{cell}:mapping_ref_axis_mismatch={ref}")

    if status in {"VERIFICADO_PLANO_CURSO_2026", "VERIFICADO_COM_SUPORTE_COMPLEMENTAR"}:
        fully_verified_cells += 1
        if not verified_refs:
            errors.append(f"{cell}:verified_cell_without_verified_mapping")
        if any(mapping_by_id.get(ref, {}).get("status") not in verified_statuses for ref in verified_refs):
            errors.append(f"{cell}:verified_cell_references_nonverified_mapping")
    elif status == "PARCIAL_AGUARDA_3T_2026":
        partial_cells += 1
        if not verified_refs or not pending_refs:
            errors.append(f"{cell}:partial_cell_requires_verified_and_pending_refs")
    elif status == "AGUARDA_AUDITORIA_PLANO_3T_2026":
        pending_cells += 1
        if not pending_refs:
            errors.append(f"{cell}:pending_cell_without_pending_mapping")
        if r.get("nivel") != "N1":
            errors.append(f"{cell}:unexpected_pending_cell_outside_N1")

# Institutional guardrails: do not silently claim full MG certification while N1 3T remains unresolved.
if pending_cells or partial_cells:
    final_status = "APROVADO_PARCIAL_COM_PENDENCIA_DOCUMENTADA_3T_5EF"
else:
    final_status = "APROVADO_ADAPTADOR_CRMG_2026"

report = {
    "validator": "validate_adaptador_crmg_2026.py",
    "adapter_version": "1.0.0",
    "status": "REPROVADO" if errors else final_status,
    "checks": {
        "atomic_mappings": len(atomic),
        "atomic_verified": verified_atomic,
        "atomic_pending_or_partial": pending_atomic,
        "coverage_cells": len(coverage),
        "fully_verified_cells": fully_verified_cells,
        "partial_cells": partial_cells,
        "pending_cells": pending_cells,
        "semantic_cells_expected": 24,
        "official_year": 2026,
    },
    "methodological_note": "Cobertura parcial no N1 não é erro: registra que habilidades de participação/qualidade ambiental ainda não foram localizadas nos Planos de Curso 2026 do 1º/2º trimestre auditados. Não se presume trimestre nem código de rede sem fonte.",
    "errors": errors,
    "warnings": warnings,
}
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
if errors:
    raise SystemExit(1)
