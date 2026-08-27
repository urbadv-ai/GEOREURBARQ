from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CONTENT = ROOT / "observatorio-cidadao-urbano-escolar" / "pedagogico" / "conteudo"
SOURCE = CONTENT / "sistema_avaliacao_aprendizagem_v1_0.json"
REPORT = CONTENT / "sistema_avaliacao_validation_report.json"

obj = json.loads(SOURCE.read_text(encoding="utf-8"))
errors: list[str] = []
warnings: list[str] = []

expected_moments = {"A0", "A1", "A2", "A3"}
expected_dims = {f"R{i}" for i in range(1, 9)}
expected_levels = {"N1", "N2", "N3"}

moments = obj.get("momentos", [])
moment_codes = [m.get("codigo") for m in moments]
if set(moment_codes) != expected_moments or len(moment_codes) != 4:
    errors.append(f"moments_expected_A0_A3_found={moment_codes}")
for m in moments:
    for field in ["codigo", "nome", "finalidade"]:
        if not m.get(field):
            errors.append(f"moment_{m.get('codigo','UNKNOWN')}:missing_{field}")

dims = obj.get("dimensoes", [])
dim_codes = [d.get("codigo") for d in dims]
if set(dim_codes) != expected_dims or len(dim_codes) != 8:
    errors.append(f"dimensions_expected_R1_R8_found={dim_codes}")
if len(dim_codes) != len(set(dim_codes)):
    errors.append("duplicate_dimension_code")

standard_weight_sum = 0
for d in dims:
    code = d.get("codigo", "UNKNOWN")
    for field in ["nome", "peso_padrao", "descritores"]:
        if d.get(field) in [None, "", {}]:
            errors.append(f"{code}:missing_{field}")
    try:
        standard_weight_sum += int(d.get("peso_padrao", 0))
    except (TypeError, ValueError):
        errors.append(f"{code}:invalid_standard_weight")
    desc = d.get("descritores", {})
    if set(desc.keys()) != {"1", "2", "3", "4"}:
        errors.append(f"{code}:descriptors_expected_1_4_found={sorted(desc.keys())}")
    if any(not str(desc.get(str(i), "")).strip() for i in range(1,5)):
        errors.append(f"{code}:blank_descriptor")

if standard_weight_sum != 100:
    errors.append(f"standard_weights_expected_100_found={standard_weight_sum}")

weights = obj.get("pesos_por_nivel", {})
if set(weights.keys()) != expected_levels:
    errors.append(f"level_weights_expected_N1_N3_found={sorted(weights.keys())}")
for level in expected_levels:
    level_weights = weights.get(level, {})
    if set(level_weights.keys()) != expected_dims:
        errors.append(f"{level}:dimension_weights_incomplete")
    try:
        total = sum(int(v) for v in level_weights.values())
    except (TypeError, ValueError):
        total = -1
    if total != 100:
        errors.append(f"{level}:weights_expected_100_found={total}")

minimum = obj.get("evidencias_minimas_por_nivel", {})
if set(minimum.keys()) != expected_levels:
    errors.append("minimum_evidence_levels_incomplete")
for level in expected_levels:
    ev = minimum.get(level, [])
    if not ev or len(ev) != len(set(ev)):
        errors.append(f"{level}:minimum_evidence_missing_or_duplicate")

fail_closed = set(obj.get("regras_fail_closed", []))
required_guards = {
    "nenhum_estudante_recebe_pontuacao_maior_por_obter_resposta_favoravel_da_autoridade",
    "quantidade_de_ocorrencias_nao_e_indicador_de_aprendizagem",
    "generalizacao_de_dado_municipal_para_bairro_ou_escola_impede_nivel_maximo_em_R2_e_R3",
    "violacao_de_privacidade_ou_seguranca_impede_nivel_maximo_em_R7",
    "atividade_de_participacao_real_sem_autorizacao_nao_pode_integrar_avaliacao_canonica",
}
if not required_guards.issubset(fail_closed):
    errors.append(f"missing_fail_closed_guards={sorted(required_guards-fail_closed)}")

for field in ["principio", "regra_calculo", "faixas_interpretacao"]:
    if not obj.get(field):
        errors.append(f"missing_{field}")

ranges = obj.get("faixas_interpretacao", {})
if set(ranges.keys()) != {"0_49", "50_69", "70_84", "85_100"}:
    errors.append(f"interpretation_ranges_unexpected={sorted(ranges.keys())}")

report = {
    "validator": "validate_sistema_avaliacao.py",
    "version": "1.0.0",
    "status": "REPROVADO" if errors else "APROVADO_ESTRUTURAL_PARA_AUDITORIA_PEDAGOGICA",
    "checks": {
        "moments": len(moments),
        "dimensions": len(dims),
        "standard_weight_sum": standard_weight_sum,
        "levels_with_weights": len(weights),
        "fail_closed_rules": len(fail_closed),
    },
    "errors": errors,
    "warnings": warnings,
}
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
if errors:
    raise SystemExit(1)
