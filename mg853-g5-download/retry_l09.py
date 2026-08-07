from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

module_path = Path(__file__).with_name("collect_sources.py")
spec = importlib.util.spec_from_file_location("g5collector_l09", module_path)
if spec is None or spec.loader is None:
    raise RuntimeError("Nao foi possivel carregar o coletor G5-L09")
collector = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = collector
spec.loader.exec_module(collector)

retry = Retry(
    total=8,
    connect=8,
    read=5,
    status=5,
    backoff_factor=2,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"GET", "HEAD"}),
    raise_on_status=False,
)
adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
collector.SESSION.mount("https://", adapter)
collector.SESSION.mount("http://", adapter)
collector.TIMEOUT = (30, 180)

lot = "G5-L09"
fonte = "F-020"
page = "https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/habitacao/programa-minha-casa-minha-vida/bases-de-dados-do-programa-minha-casa-minha-vida"

collector.write_semantic_crosswalk()
collector.crawl_official_files(
    lot,
    fonte,
    [page],
    [
        "mcmv", "minha_casa", "minha-casa", "subsidiado", "financ", "fgts",
        "snhis", "regularidade", "dicion", "empreendimento", "habitacao", "habitação",
    ],
    max_file_bytes=2_000 * 1024 * 1024,
)

# Enderecos oficiais confirmados na pagina vigente, preservados como redundancia controlada.
for url, name, obs in [
    (
        "https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/habitacao/programa-minha-casa-minha-vida/arquivos/mcmv_subsidiado_202606302.zip",
        "mcmv_subsidiado_202606302.zip",
        "MCMV subsidiado - empreendimentos; edicao oficial publicada em 2026",
    ),
    (
        "https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/habitacao/programa-minha-casa-minha-vida/arquivos/mcmv_financ_sintetico_20260724.zip",
        "mcmv_financ_sintetico_20260724.zip",
        "MCMV financiado FGTS - dados sinteticos municipais; edicao oficial publicada em 2026",
    ),
    (
        "https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/habitacao/arquivos-1/Dicionarios_SNH_2025_10_09.pdf",
        "Dicionarios_SNH_2025_10_09.pdf",
        "Dicionario oficial comum aos conjuntos habitacionais e SNHIS",
    ),
]:
    collector.download(lot, fonte, url, name, observation=obs)

(collector.ensure_lot(lot) / "MODO_AQUISICAO.txt").write_text(
    "AQUISICAO RESILIENTE DA PAGINA OFICIAL, DOS CONJUNTOS MCMV E DOS DICIONARIOS. "
    "O relatorio dinamico ou arquivo de regularidade do SNHIS e preservado quando descoberto na pagina; "
    "a consulta semanal detalhada permanece objeto do snapshot temporal. "
    "E vedada qualquer estimativa propria de deficit habitacional municipal.\n",
    encoding="utf-8",
)
collector.finalize()
