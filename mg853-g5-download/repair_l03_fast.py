from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

module_path = Path(__file__).with_name("collect_sources.py")
spec = importlib.util.spec_from_file_location("g5collector_l03_fast", module_path)
if spec is None or spec.loader is None:
    raise RuntimeError("Nao foi possivel carregar o coletor G5-L03")
collector = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = collector
spec.loader.exec_module(collector)

retry = Retry(total=4, connect=4, read=2, status=2, backoff_factor=1,
              status_forcelist=(429, 500, 502, 503, 504),
              allowed_methods=frozenset({"GET", "HEAD"}), raise_on_status=False)
adapter = HTTPAdapter(max_retries=retry)
collector.SESSION.mount("https://", adapter)
collector.TIMEOUT = (15, 45)

lot, fonte = "G5-L03", "F-015"
pages = [
    "https://imrs.fjp.mg.gov.br/",
    "https://imrs.fjp.mg.gov.br/consultas/",
    "https://imrs.fjp.mg.gov.br/sobre/",
    "https://fjp.mg.gov.br/servicos-fjp/consultar-o-indice-mineiro-de-responsabilidade-social-imrs/",
]
collector.write_semantic_crosswalk()
links = []
for idx, page in enumerate(pages, start=1):
    collector.save_text(lot, fonte, page, f"pagina_oficial_vigente_{idx:02d}.html",
                        observation="Rota oficial vigente da Plataforma IMRS/FJP")
    try:
        links.extend(collector.extract_links(page))
    except Exception as exc:
        collector.record_failure(lot, fonte, "INVENTARIO_LINKS", page, exc)
collector.write_links(lot, "inventario_links_oficiais_vigentes.csv", {x["url"]: x for x in links}.values())
(collector.ensure_lot(lot) / "MODO_AQUISICAO.txt").write_text(
    "PLATAFORMA, CONSULTA, PAGINA SOBRE E SERVICO OFICIAL FJP PRESERVADOS NAS ROTAS VIGENTES. "
    "As rotas legadas com letras maiusculas foram classificadas como superadas. "
    "A exportacao CSV sera executada apenas para os indicadores aprovados na matriz de admissao, durante o snapshot.\n",
    encoding="utf-8",
)
collector.finalize()
