from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OCUE = ROOT / "observatorio-cidadao-urbano-escolar"
GOV = OCUE / "pedagogico" / "governanca"
SOURCE = GOV / "REGISTRO_MESTRE_EXECUCAO_v1_1.json"
REPORT = GOV / "registro_mestre_validation_report.json"

obj = json.loads(SOURCE.read_text(encoding="utf-8"))
errors: list[str] = []
warnings: list[str] = []

expected_phase_targets = {"P1":55,"P2":68,"P3":75,"P4":85,"P5":90,"P6":95,"P7":100}
expected_counts = {"P1":8,"P2":8,"P3":9,"P4":10,"P5":9,"P6":5,"P7":15}
allowed_status = {"NAO_INICIADO","EM_EXECUCAO","PARCIAL_VERIFICADO","VERIFICADO","BLOQUEADO"}

if obj.get("version") != "1.1.0":
    errors.append(f"registry_version_expected_1.1.0_found={obj.get('version')}")
if obj.get("supersedes") != "REGISTRO_MESTRE_EXECUCAO_v1_0.json":
    errors.append("registry_v1_1_must_reference_superseded_v1_0")

phases = obj.get("fases", [])
deliverables = obj.get("entregaveis", [])
phase_by_id = {p.get("fase_id"): p for p in phases}

if set(phase_by_id) != set(expected_phase_targets) or len(phases) != 7:
    errors.append(f"phases_expected_P1_P7_found={sorted(phase_by_id)}")

for pid, target in expected_phase_targets.items():
    p = phase_by_id.get(pid, {})
    if p.get("alvo_roadmap_percentual") != target:
        errors.append(f"{pid}:target_expected_{target}_found={p.get('alvo_roadmap_percentual')}")
    refs = p.get("entregaveis", [])
    if len(refs) != expected_counts[pid]:
        errors.append(f"{pid}:deliverable_refs_expected_{expected_counts[pid]}_found={len(refs)}")
    if len(refs) != len(set(refs)):
        errors.append(f"{pid}:duplicate_deliverable_ref")

ids = [d.get("id", "") for d in deliverables]
if len(deliverables) != sum(expected_counts.values()):
    errors.append(f"deliverables_expected_{sum(expected_counts.values())}_found={len(deliverables)}")
if len(ids) != len(set(ids)):
    errors.append("duplicate_deliverable_id")
if any(not re.fullmatch(r"P[1-7]-D\d{2}", x or "") for x in ids):
    errors.append("invalid_deliverable_id_format")

d_by_id = {d["id"]: d for d in deliverables if d.get("id")}
all_refs = []
for pid, p in phase_by_id.items():
    for ref in p.get("entregaveis", []):
        all_refs.append(ref)
        if ref not in d_by_id:
            errors.append(f"{pid}:unknown_deliverable_ref={ref}")
        elif d_by_id[ref].get("fase") != pid:
            errors.append(f"{ref}:phase_mismatch={d_by_id[ref].get('fase')} expected={pid}")
if set(all_refs) != set(ids):
    errors.append(f"phase_reference_set_mismatch missing={sorted(set(ids)-set(all_refs))} extra={sorted(set(all_refs)-set(ids))}")

for d in deliverables:
    did = d.get("id", "UNKNOWN")
    status = d.get("status")
    frac = d.get("fracao_conclusao")
    if not str(d.get("nome", "")).strip():
        errors.append(f"{did}:missing_name")
    if status not in allowed_status:
        errors.append(f"{did}:invalid_status={status}")
    if not isinstance(frac, (int, float)) or not 0 <= frac <= 1:
        errors.append(f"{did}:invalid_fraction={frac}")
        continue
    if status == "NAO_INICIADO" and frac != 0:
        errors.append(f"{did}:not_started_fraction_must_be_zero")
    if status == "VERIFICADO" and frac != 1:
        errors.append(f"{did}:verified_fraction_must_be_one")
    if status == "PARCIAL_VERIFICADO" and not (0 < frac < 1):
        errors.append(f"{did}:partial_fraction_must_be_between_zero_and_one")
    if status in {"VERIFICADO", "PARCIAL_VERIFICADO"}:
        evs = d.get("evidencias", [])
        if not evs:
            errors.append(f"{did}:verified_or_partial_without_evidence")
        for ev in evs:
            p = OCUE / ev
            if not p.exists():
                errors.append(f"{did}:evidence_path_missing={ev}")
        if not str(d.get("gate", "")).strip():
            errors.append(f"{did}:verified_or_partial_without_gate")
    if not str(d.get("pendencia", "")).strip():
        errors.append(f"{did}:missing_pending_or_completion_note")

p1 = [d for d in deliverables if d.get("fase") == "P1"]
p1_sum = sum(float(d.get("fracao_conclusao", 0)) for d in p1)
p1_pct = p1_sum / len(p1) * 100 if p1 else 0
metrics = obj.get("metricas_fase_1", {})
if abs(p1_sum - float(metrics.get("soma_fracoes", -999))) > 1e-9:
    errors.append(f"phase1_sum_mismatch calculated={p1_sum} stored={metrics.get('soma_fracoes')}")
if int(metrics.get("quantidade_entregaveis", -1)) != len(p1):
    errors.append("phase1_count_mismatch")
if abs(p1_pct - float(metrics.get("conclusao_percentual", -999))) > 1e-9:
    errors.append(f"phase1_percent_mismatch calculated={p1_pct} stored={metrics.get('conclusao_percentual')}")

# Explicit safeguards for the two partial P1 calculations.
if abs(float(d_by_id.get("P1-D06", {}).get("fracao_conclusao", -1)) - 0.8125) > 1e-9:
    errors.append("P1-D06_CRMG_fraction_must_be_0.8125_until_adapter_is_updated")
if abs(float(d_by_id.get("P1-D07", {}).get("fracao_conclusao", -1)) - 0.5) > 1e-9:
    errors.append("P1-D07_integrated_matrix_fraction_must_be_0.5_until_explicit_matrix_exists")

# Evidence corrections caught by the rejected v1.0 register must remain fixed.
forbidden_evidence = {
    "pedagogico/conteudo/arquitetura_unidades_integradoras_v1_0.json",
    "pedagogico/PAP_OCUE_v1_0.md",
    "templates/TEMPLATE_TERMO_CONSENTIMENTO_RESPONSAVEL_v1_0.md",
    "templates/TEMPLATE_TERMO_ASSENTIMENTO_ESTUDANTE_v1_0.md",
    "templates/TEMPLATE_TERMO_CIENCIA_PROFISSIONAL_v1_0.md",
    "formularios/especificacoes/",
}
all_evidence = {ev for d in deliverables for ev in d.get("evidencias", [])}
if forbidden_evidence & all_evidence:
    errors.append(f"known_nonexistent_evidence_reintroduced={sorted(forbidden_evidence & all_evidence)}")
if d_by_id.get("P4-D05", {}).get("fracao_conclusao") != 0:
    errors.append("P4-D05_must_remain_zero_until_real_consent_assent_artifacts_exist")

if obj.get("branch") != "conteudo-programatico-v1":
    errors.append("registry_branch_must_be_conteudo-programatico-v1")
if len(obj.get("regras_de_controle", [])) < 9:
    errors.append("insufficient_control_rules")
if not obj.get("pendencias_criticas_imediatas"):
    errors.append("missing_critical_open_items")
if not obj.get("auditoria_de_evidencias_v1_1", {}).get("correcoes"):
    errors.append("missing_v1_1_evidence_audit_record")

report = {
    "validator": "validate_registro_mestre_execucao.py",
    "registry_version": obj.get("version"),
    "status": "REPROVADO" if errors else "APROVADO_REGISTRO_MESTRE_RASTREAVEL",
    "checks": {
        "phases": len(phases),
        "deliverables": len(deliverables),
        "phase1_deliverables": len(p1),
        "phase1_fraction_sum": p1_sum,
        "phase1_completion_percent": p1_pct,
        "verified": sum(1 for d in deliverables if d.get("status") == "VERIFICADO"),
        "partial_verified": sum(1 for d in deliverables if d.get("status") == "PARCIAL_VERIFICADO"),
        "not_started": sum(1 for d in deliverables if d.get("status") == "NAO_INICIADO"),
        "evidence_paths_checked": sum(len(d.get("evidencias", [])) for d in deliverables if d.get("status") in {"VERIFICADO", "PARCIAL_VERIFICADO"}),
        "known_false_evidence_reintroduced": bool(forbidden_evidence & all_evidence)
    },
    "errors": errors,
    "warnings": warnings,
}
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
if errors:
    raise SystemExit(1)
