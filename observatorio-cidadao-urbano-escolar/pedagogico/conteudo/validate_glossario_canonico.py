from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OCUE = ROOT / "observatorio-cidadao-urbano-escolar"
CONTENT = OCUE / "pedagogico" / "conteudo"
GLOSSARY = CONTENT / "glossario_canonico_direitos_deveres_cidade_v1_0.csv"
SOURCES = CONTENT / "glossario_fontes_v1_0.json"
REPORT = CONTENT / "glossario_canonico_validation_report.json"

errors: list[str] = []

with GLOSSARY.open("r", encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))
sources = json.loads(SOURCES.read_text(encoding="utf-8"))
valid_sources = set(sources.get("fontes", {}))
valid_levels = {"N1", "N2", "N3"}

required_columns = {
    "termo_codigo", "termo", "definicao_operacional", "uso_pedagogico_permitido",
    "uso_indevido_evitar", "conceitos_relacionados", "fonte_base",
    "niveis_aplicaveis", "status"
}
if not rows:
    errors.append("glossary_empty")
elif required_columns - set(rows[0]):
    errors.append(f"missing_columns={sorted(required_columns-set(rows[0]))}")

required_terms = {
    "Cidade", "Território", "Cidadania", "Direito", "Dever", "Função social da cidade",
    "Função social da propriedade urbana", "Cidade sustentável", "Observação cidadã",
    "Evidência", "Fonte", "Dado", "Indicador", "Mapa", "Escala", "Saneamento urbano",
    "Mobilidade urbana", "Acessibilidade", "Drenagem urbana", "Resíduos urbanos",
    "Desigualdade territorial", "Risco urbano", "Política urbana", "Planejamento urbano",
    "Plano diretor", "Governança urbana", "Participação social", "Controle social",
    "Acompanhamento", "ODS", "IDSC-BR"
}

codes, terms = set(), set()
for r in rows:
    code = (r.get("termo_codigo") or "").strip()
    term = (r.get("termo") or "").strip()
    if code in codes:
        errors.append(f"duplicate_code={code}")
    if term.casefold() in terms:
        errors.append(f"duplicate_term={term}")
    codes.add(code); terms.add(term.casefold())

    for field in required_columns:
        if not (r.get(field) or "").strip():
            errors.append(f"{code}:missing_{field}")
    if len((r.get("definicao_operacional") or "").strip()) < 40:
        errors.append(f"{code}:definition_too_short")
    if len((r.get("uso_pedagogico_permitido") or "").strip()) < 20:
        errors.append(f"{code}:allowed_use_too_short")
    if len((r.get("uso_indevido_evitar") or "").strip()) < 20:
        errors.append(f"{code}:misuse_guardrail_too_short")

    levels = {x.strip() for x in (r.get("niveis_aplicaveis") or "").split(";") if x.strip()}
    if not levels or levels - valid_levels:
        errors.append(f"{code}:invalid_levels={sorted(levels-valid_levels)}")

    refs = {x.strip() for x in (r.get("fonte_base") or "").split(";") if x.strip()}
    unknown = refs - valid_sources
    if unknown:
        errors.append(f"{code}:unknown_sources={sorted(unknown)}")
    if r.get("status") != "VERIFICADO_ESTRUTURAL":
        errors.append(f"{code}:invalid_status={r.get('status')}")

    lowered = " ".join(r.values()).casefold()
    for forbidden in ["todo", "a definir", "pendente"]:
        if forbidden in lowered:
            errors.append(f"{code}:forbidden_placeholder={forbidden}")

missing_terms = sorted(t for t in required_terms if t.casefold() not in terms)
if missing_terms:
    errors.append(f"required_terms_missing={missing_terms}")
if len(rows) < 30:
    errors.append(f"minimum_terms_30_found={len(rows)}")

# Every internal provenance target must exist.
for key, meta in sources.get("fontes", {}).items():
    if meta.get("tipo") == "interna_versionada":
        path = OCUE / meta.get("path", "")
        if not path.exists():
            errors.append(f"source_{key}:internal_path_missing={meta.get('path')}")
    elif meta.get("tipo") in {"oficial_externa", "fonte_metodologica_externa"}:
        if not (meta.get("url") or "").startswith("https://"):
            errors.append(f"source_{key}:invalid_url")

report = {
    "validator": "validate_glossario_canonico.py",
    "status": "REPROVADO" if errors else "APROVADO",
    "checks": {
        "terms": len(rows),
        "minimum_terms": 30,
        "required_terms": len(required_terms),
        "source_keys": len(valid_sources),
        "levels": sorted(valid_levels),
        "guardrail": "definicoes_operacionais_nao_substituem_parecer_juridico"
    },
    "errors": errors,
}
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
if errors:
    raise SystemExit(1)
