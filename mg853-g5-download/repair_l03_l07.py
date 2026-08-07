from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

module_path = Path(__file__).with_name("collect_sources.py")
spec = importlib.util.spec_from_file_location("g5collector_repairs", module_path)
if spec is None or spec.loader is None:
    raise RuntimeError("Nao foi possivel carregar o coletor G5")
collector = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = collector
spec.loader.exec_module(collector)

retry = Retry(
    total=6,
    connect=6,
    read=4,
    status=4,
    backoff_factor=1.5,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"GET", "HEAD"}),
    raise_on_status=False,
)
adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
collector.SESSION.mount("https://", adapter)
collector.SESSION.mount("http://", adapter)
collector.TIMEOUT = (20, 120)

repair = os.environ.get("REPAIR_ID", "").strip().upper()
collector.write_semantic_crosswalk()

if repair == "G5-L03":
    lot, fonte = "G5-L03", "F-015"
    pages = [
        "https://imrs.fjp.mg.gov.br/",
        "https://imrs.fjp.mg.gov.br/consultas/",
        "https://imrs.fjp.mg.gov.br/sobre/",
        "https://fjp.mg.gov.br/servicos-fjp/consultar-o-indice-mineiro-de-responsabilidade-social-imrs/",
        "https://imrs.fjp.mg.gov.br/Home/IMRS",
    ]
    links = []
    for idx, page in enumerate(pages, start=1):
        collector.save_text(
            lot,
            fonte,
            page,
            f"pagina_oficial_atual_{idx:02d}.html",
            observation="Endpoint oficial vigente validado após substituição de rota legada",
        )
        try:
            links.extend(collector.extract_links(page))
        except Exception as exc:
            collector.record_failure(lot, fonte, "INVENTARIO_LINKS", page, exc)
    collector.write_links(lot, "inventario_links_oficiais_atual.csv", {row["url"]: row for row in links}.values())
    (collector.ensure_lot(lot) / "MODO_AQUISICAO.txt").write_text(
        "CATALOGO, CONSULTA, PAGINA SOBRE, SERVICO FJP E REPOSITORIO METODOLOGICO OFICIAIS PRESERVADOS. "
        "A exportacao CSV sera realizada somente para os indicadores admitidos semanticamente, durante o snapshot. "
        "As rotas legadas /Consultas e /Metodologia foram classificadas como superadas, sem impacto na fonte vigente.\n",
        encoding="utf-8",
    )

elif repair == "G5-L07":
    lot, fonte = "G5-L07", "F-006"
    pages = [
        "https://geoportal.meioambiente.mg.gov.br/",
        "https://geoportal.meioambiente.mg.gov.br/webservices",
        "https://geoserver.meioambiente.mg.gov.br/web/",
        "https://idesisema.meioambiente.mg.gov.br/geonetwork/srv/search?type=dataset",
    ]
    for idx, page in enumerate(pages, start=1):
        collector.save_text(
            lot,
            fonte,
            page,
            f"portal_oficial_atual_{idx:02d}.html",
            observation="Portal IDE-Sisema 3.0, geoserviços e catálogo oficial vigentes",
        )
    services = {
        "wms_getcapabilities.xml": "https://geoserver.meioambiente.mg.gov.br/ows?service=WMS&request=GetCapabilities&version=1.3.0",
        "wfs_getcapabilities.xml": "https://geoserver.meioambiente.mg.gov.br/ows?service=WFS&request=GetCapabilities&version=2.0.0",
        "wcs_getcapabilities.xml": "https://geoserver.meioambiente.mg.gov.br/ows?service=WCS&request=GetCapabilities&version=2.0.1",
        "csw_getcapabilities.xml": "https://idesisema.meioambiente.mg.gov.br/geonetwork/srv/por/csw?service=CSW&version=2.0.2&request=GetCapabilities",
    }
    for filename, url in services.items():
        collector.download(
            lot,
            fonte,
            url,
            filename,
            mode="CAPABILITIES_OFICIAL_VIGENTE",
            required=True,
            max_bytes=200 * 1024 * 1024,
            observation="Endpoint oficial publicado no Geoportal IDE-Sisema 3.0",
        )
    (collector.ensure_lot(lot) / "MODO_AQUISICAO.txt").write_text(
        "PORTAL IDE-SISEMA 3.0, GEOSERVER VIGENTE, CATALOGO E CAPABILITIES WMS/WFS/WCS/CSW PRESERVADOS. "
        "Os endpoints antigos sob /geoserver/ows foram substituidos por https://geoserver.meioambiente.mg.gov.br/ows. "
        "A extracao das cinco familias tematicas aprovadas sera congelada na etapa de snapshot.\n",
        encoding="utf-8",
    )
else:
    raise SystemExit(f"REPAIR_ID invalido: {repair}")

collector.finalize()
