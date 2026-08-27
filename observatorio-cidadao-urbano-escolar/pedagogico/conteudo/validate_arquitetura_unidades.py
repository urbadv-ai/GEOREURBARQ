from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CONTENT = ROOT / "observatorio-cidadao-urbano-escolar" / "pedagogico" / "conteudo"
SRC = CONTENT / "arquitetura_unidades_perfis_saida_v1_0.json"
REPORT = CONTENT / "unit_architecture_validation_report.json"

obj = json.loads(SRC.read_text(encoding="utf-8"))
errors: list[str] = []
warnings: list[str] = []

units = obj.get("unidades", [])
levels = obj.get("niveis", [])
expected_units = {"U1", "U2", "U3", "U4"}
expected_axes = {f"E{i}" for i in range(1, 9)}
expected_levels = {"N1", "N2", "N3"}
expected_hours = {"N1": 12, "N2": 16, "N3": 20}
valid_cycle = {"CONHECER", "OBSERVAR", "MAPEAR", "CLASSIFICAR", "PROPOR", "PARTICIPAR", "ACOMPANHAR"}

unit_codes = [u.get("codigo") for u in units]
if set(unit_codes) != expected_units or len(unit_codes) != 4:
    errors.append(f"units_expected_U1_U4_found={unit_codes}")

axis_usage: list[str] = []
cycle_usage: set[str] = set()
unit_by_code = {u.get("codigo"): u for u in units}
for u in units:
    code = u.get("codigo", "UNKNOWN")
    for field in ["nome", "eixos", "pergunta_essencial", "etapas_ciclo_dominantes", "conceitos_limiar", "pre_requisitos", "habilita"]:
        if u.get(field) in (None, "", [] ) and field not in {"pre_requisitos", "habilita"}:
            errors.append(f"{code}:missing_{field}")
    axes = u.get("eixos", [])
    if len(axes) != 2:
        errors.append(f"{code}:expected_2_axes_found={axes}")
    axis_usage.extend(axes)
    bad_axes = set(axes) - expected_axes
    if bad_axes:
        errors.append(f"{code}:invalid_axes={sorted(bad_axes)}")
    stages = set(u.get("etapas_ciclo_dominantes", []))
    bad_stages = stages - valid_cycle
    if bad_stages:
        errors.append(f"{code}:invalid_cycle_stages={sorted(bad_stages)}")
    cycle_usage |= stages

if set(axis_usage) != expected_axes or len(axis_usage) != 8:
    errors.append(f"axis_partition_invalid_usage={axis_usage}")
if len(axis_usage) != len(set(axis_usage)):
    errors.append("axis_reused_across_units")
if cycle_usage != valid_cycle:
    errors.append(f"cycle_coverage_missing={sorted(valid_cycle-cycle_usage)}")

# Dependency graph must be acyclic, resolvable and progressively ordered.
visiting: set[str] = set()
visited: set[str] = set()

def dfs(code: str):
    if code in visiting:
        errors.append(f"dependency_cycle_detected_at={code}")
        return
    if code in visited:
        return
    visiting.add(code)
    unit = unit_by_code.get(code)
    if unit is None:
        errors.append(f"dependency_unknown_unit={code}")
    else:
        for dep in unit.get("pre_requisitos", []):
            if dep not in expected_units:
                errors.append(f"{code}:unknown_prerequisite={dep}")
            else:
                dfs(dep)
        for dest in unit.get("habilita", []):
            if dest not in expected_units:
                errors.append(f"{code}:unknown_habilita={dest}")
    visiting.remove(code)
    visited.add(code)

for code in expected_units:
    dfs(code)

required_prereqs = {
    "U1": set(),
    "U2": {"U1"},
    "U3": {"U1", "U2"},
    "U4": {"U1", "U2", "U3"},
}
for code, expected in required_prereqs.items():
    found = set(unit_by_code.get(code, {}).get("pre_requisitos", []))
    if found != expected:
        errors.append(f"{code}:prerequisites_expected={sorted(expected)} found={sorted(found)}")

level_codes = [n.get("codigo") for n in levels]
if set(level_codes) != expected_levels or len(level_codes) != 3:
    errors.append(f"levels_expected_N1_N3_found={level_codes}")

for n in levels:
    code = n.get("codigo", "UNKNOWN")
    for field in ["etapa", "carga_horaria_total", "distribuicao_horas", "perfil_saida", "produto_final", "nivel_autonomia"]:
        if not n.get(field):
            errors.append(f"{code}:missing_{field}")
    total = n.get("carga_horaria_total")
    if total != expected_hours.get(code):
        errors.append(f"{code}:total_hours_expected={expected_hours.get(code)} found={total}")
    dist = n.get("distribuicao_horas", {})
    if set(dist) != expected_units:
        errors.append(f"{code}:hour_distribution_missing_units={sorted(expected_units-set(dist))}")
    if sum(dist.values()) != total:
        errors.append(f"{code}:hour_distribution_sum={sum(dist.values())} total={total}")
    profile = n.get("perfil_saida", [])
    if len(profile) < 5:
        errors.append(f"{code}:exit_profile_too_short={len(profile)}")
    if any(not str(x).strip() for x in profile):
        errors.append(f"{code}:blank_exit_profile_item")

if not obj.get("regras_transversais") or len(obj.get("regras_transversais", [])) < 5:
    errors.append("insufficient_cross_cutting_rules")

status = "REPROVADO" if errors else "APROVADO_ESTRUTURAL_PARA_BLUEPRINT_DIDATICO"
report = {
    "validator": "validate_arquitetura_unidades.py",
    "version": obj.get("version"),
    "status": status,
    "checks": {
        "units": len(units),
        "axes_partitioned": len(set(axis_usage)),
        "levels": len(levels),
        "cycle_stages_covered": len(cycle_usage),
        "hours": {n.get("codigo"): n.get("carga_horaria_total") for n in levels},
        "dependency_graph_acyclic": not any("dependency_cycle" in e for e in errors),
    },
    "errors": errors,
    "warnings": warnings,
}
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
if errors:
    raise SystemExit(1)
