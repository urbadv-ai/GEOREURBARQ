from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GOV = ROOT / "observatorio-cidadao-urbano-escolar" / "pedagogico" / "governanca"
OLD = json.loads((GOV / "maturidade_projeto_v1_0.json").read_text(encoding="utf-8"))
NEW = json.loads((GOV / "maturidade_projeto_v1_1.json").read_text(encoding="utf-8"))
REG = json.loads((GOV / "REGISTRO_MESTRE_EXECUCAO_v1_0.json").read_text(encoding="utf-8"))
REPORT = GOV / "maturidade_validation_report.json"

errors: list[str] = []
warnings: list[str] = []

def by_id(obj):
    return {d["id"]: d for d in obj.get("dimensoes", [])}

old_d = by_id(OLD)
new_d = by_id(NEW)
expected_ids = {f"D{i}" for i in range(1,12)}
if set(new_d) != expected_ids or len(new_d) != 11:
    errors.append(f"dimensions_expected_D1_D11_found={sorted(new_d)}")
if set(old_d) != expected_ids:
    errors.append("old_snapshot_dimension_set_changed_or_invalid")

weight_sum = sum(float(d.get("peso", 0)) for d in new_d.values())
if abs(weight_sum - 100) > 1e-9:
    errors.append(f"weight_sum_expected_100_found={weight_sum}")

calc_total = 0.0
for did, d in new_d.items():
    weight = float(d.get("peso", 0))
    score = float(d.get("score", 0))
    contribution = float(d.get("contribuicao", 0))
    expected_contribution = weight * score / 100
    if abs(contribution - expected_contribution) > 1e-9:
        errors.append(f"{did}:contribution_mismatch stored={contribution} expected={expected_contribution}")
    calc_total += contribution

stored_precise = float(NEW.get("score_calculado_preciso", -1))
if abs(calc_total - stored_precise) > 1e-9:
    errors.append(f"global_score_mismatch calculated={calc_total} stored={stored_precise}")
if round(stored_precise, 2) != float(NEW.get("score_atual_duas_casas", -1)):
    errors.append("two_decimal_score_mismatch")
if round(stored_precise) != int(NEW.get("score_atual_arredondado", -1)):
    errors.append("rounded_score_mismatch")

# Only D4 is allowed to change in this snapshot.
for did in expected_ids - {"D4"}:
    for field in ["peso", "score", "contribuicao"]:
        if float(new_d[did][field]) != float(old_d[did][field]):
            errors.append(f"{did}:{field}_must_remain_equal_to_v1_0")

reg_p1 = float(REG.get("metricas_fase_1", {}).get("conclusao_percentual", -1))
if abs(float(new_d["D4"].get("score", -1)) - reg_p1) > 1e-9:
    errors.append(f"D4_must_equal_registry_phase1_completion stored={new_d['D4'].get('score')} registry={reg_p1}")

old_score = float(OLD.get("score_atual", -1))
variation = stored_precise - old_score
if abs(variation - float(NEW.get("metodologia_atualizacao", {}).get("variacao_global_pontos_percentuais", -1))) > 1e-9:
    errors.append("global_variation_mismatch")

next_target = float(NEW.get("proximo_alvo_roadmap", -1))
gap = next_target - stored_precise
if abs(gap - float(NEW.get("distancia_para_proximo_alvo_pontos_percentuais", -1))) > 1e-9:
    errors.append("next_target_gap_mismatch")

if 50 <= stored_precise < 75:
    expected_class = "CONSTRUCAO_INSTRUCIONAL"
elif stored_precise < 50:
    expected_class = "FUNDACAO_E_ARQUITETURA"
elif stored_precise < 85:
    expected_class = "FORMACAO_DOCENTE_PILOTO"
elif stored_precise < 95:
    expected_class = "PILOTO_EM_SALA"
elif stored_precise < 100:
    expected_class = "ESCALA_CONTROLADA"
else:
    expected_class = "RELEASE_V1_0"
if NEW.get("classificacao_atual") != expected_class:
    errors.append(f"classification_mismatch expected={expected_class} stored={NEW.get('classificacao_atual')}")

if NEW.get("status") != "AUDITADO_NA_BRANCH_NAO_HOMOLOGADO_EM_MAIN":
    errors.append("snapshot_must_preserve_branch_not_main_status")
if any(m.get("status") != "NAO_LIBERADO" for m in NEW.get("marcos", [])):
    errors.append("no_milestone_can_be_released_at_current_state")
if not NEW.get("gates_abertos_que_impedem_fechamento_P1"):
    errors.append("missing_open_phase1_gates")

report = {
    "validator": "validate_maturidade_projeto.py",
    "snapshot_version": NEW.get("version"),
    "status": "REPROVADO" if errors else "APROVADO_SNAPSHOT_MATURIDADE_AUDITADO_NA_BRANCH",
    "checks": {
        "weights_sum": weight_sum,
        "score_previous": old_score,
        "score_current_precise": stored_precise,
        "score_current_2dp": round(stored_precise, 2),
        "variation_pp": variation,
        "phase1_completion_percent": reg_p1,
        "next_roadmap_target": next_target,
        "gap_to_next_target_pp": gap,
        "only_dimension_updated": "D4"
    },
    "errors": errors,
    "warnings": warnings
}
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
if errors:
    raise SystemExit(1)
