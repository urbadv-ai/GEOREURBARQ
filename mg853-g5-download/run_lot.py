from __future__ import annotations

import importlib.util
import os
from pathlib import Path

module_path = Path(__file__).with_name("collect_sources.py")
spec = importlib.util.spec_from_file_location("g5collector", module_path)
if spec is None or spec.loader is None:
    raise RuntimeError("Nao foi possivel carregar o coletor G5")
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)

collector.TIMEOUT = (15, 45)
lot = os.environ.get("LOT_ID", "").strip().upper()
collectors = {
    "G5-L01": collector.collect_l01,
    "G5-L02": collector.collect_l02,
    "G5-L03": collector.collect_l03,
    "G5-L04": collector.collect_l04,
    "G5-L05": collector.collect_l05,
    "G5-L06": collector.collect_l06,
    "G5-L07": collector.collect_l07,
    "G5-L08": collector.collect_l08,
    "G5-L09": collector.collect_l09,
}
if lot not in collectors:
    raise SystemExit(f"LOT_ID invalido: {lot}")

print(f"INICIO {lot}", flush=True)
collector.write_semantic_crosswalk()
try:
    collectors[lot]()
except Exception as exc:
    collector.record_failure(lot, "DESCONHECIDA", "EXECUCAO_LOTE", "", exc,
                             "Falha controlada no processo independente")
collector.finalize()
print(f"FIM {lot}", flush=True)
