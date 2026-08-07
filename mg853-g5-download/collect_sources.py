from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path("mg853-g5-download/output")
ROOT.mkdir(parents=True, exist_ok=True)
USER_AGENT = "MG853-G5-OABMG/3.0 (+auditoria de fontes oficiais)"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})
TIMEOUT = (30, 300)


@dataclass
class Record:
    lote_id: str
    fonte_id: str
    modalidade: str
    url_solicitada: str
    url_final: str
    arquivo: str
    status_http: int | str
    tamanho_bytes: int
    sha256: str
    data_hora_utc: str
    resultado: str
    observacao: str


records: list[Record] = []
errors: list[dict[str, str]] = []


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe_name(url: str, fallback: str = "arquivo") -> str:
    name = unquote(Path(urlparse(url).path).name) or fallback
    name = re.sub(r"[^A-Za-z0-9._()-]+", "_", name).strip("_")
    return name[:220] or fallback


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def ensure_lot(lot: str) -> Path:
    p = ROOT / lot
    p.mkdir(parents=True, exist_ok=True)
    return p


def record_failure(lot: str, fonte: str, mode: str, url: str, exc: Exception, obs: str = "") -> None:
    errors.append({
        "lote_id": lot,
        "fonte_id": fonte,
        "modalidade": mode,
        "url": url,
        "erro": type(exc).__name__,
        "mensagem": str(exc)[:1000],
        "observacao": obs,
        "data_hora_utc": now_utc(),
    })


def download(lot: str, fonte: str, url: str, filename: str | None = None,
             mode: str = "DOWNLOAD_BINARIO_INTEGRAL", required: bool = True,
             max_bytes: int | None = None, observation: str = "") -> Path | None:
    out_dir = ensure_lot(lot)
    temp = out_dir / (".__tmp__" + (filename or safe_name(url)))
    try:
        with SESSION.get(url, stream=True, timeout=TIMEOUT, allow_redirects=True) as r:
            status = r.status_code
            r.raise_for_status()
            length = int(r.headers.get("content-length") or 0)
            if max_bytes and length and length > max_bytes:
                records.append(Record(lot, fonte, mode, url, r.url, "", status, length, "", now_utc(),
                                      "CATALOGADO_NAO_BAIXADO_LIMITE", observation or f"Conteúdo acima do limite de {max_bytes} bytes"))
                return None
            name = filename or safe_name(r.url, safe_name(url))
            final = out_dir / name
            total = 0
            with temp.open("wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if max_bytes and total > max_bytes:
                        raise RuntimeError(f"arquivo excedeu limite controlado de {max_bytes} bytes")
                    f.write(chunk)
            temp.replace(final)
            digest = sha256_file(final)
            records.append(Record(lot, fonte, mode, url, r.url, final.name, status, total, digest,
                                  now_utc(), "BAIXADO_INTEGRALMENTE", observation))
            return final
    except Exception as exc:
        if temp.exists():
            temp.unlink(missing_ok=True)
        record_failure(lot, fonte, mode, url, exc, observation)
        records.append(Record(lot, fonte, mode, url, "", filename or safe_name(url), "ERRO", 0, "",
                              now_utc(), "FALHA_DOWNLOAD" if required else "FALHA_NAO_BLOQUEADORA", observation))
        return None


def save_text(lot: str, fonte: str, url: str, filename: str,
              mode: str = "CATALOGO_OFICIAL_INTEGRAL", observation: str = "") -> Path | None:
    out_dir = ensure_lot(lot)
    try:
        r = SESSION.get(url, timeout=TIMEOUT, allow_redirects=True)
        r.raise_for_status()
        path = out_dir / filename
        path.write_text(r.text, encoding="utf-8")
        digest = sha256_file(path)
        records.append(Record(lot, fonte, mode, url, r.url, filename, r.status_code,
                              path.stat().st_size, digest, now_utc(), "CATALOGO_BAIXADO", observation))
        return path
    except Exception as exc:
        record_failure(lot, fonte, mode, url, exc, observation)
        records.append(Record(lot, fonte, mode, url, "", filename, "ERRO", 0, "", now_utc(),
                              "FALHA_CATALOGO", observation))
        return None


def extract_links(url: str) -> list[dict[str, str]]:
    r = SESSION.get(url, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(r.url, a.get("href", "").strip())
        if href in seen:
            continue
        seen.add(href)
        found.append({"url": href, "texto": " ".join(a.get_text(" ", strip=True).split())})
    return found


def write_links(lot: str, filename: str, links: Iterable[dict[str, str]]) -> Path:
    path = ensure_lot(lot) / filename
    rows = list(links)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["url", "texto"])
        w.writeheader()
        w.writerows(rows)
    return path


def crawl_official_files(lot: str, fonte: str, pages: list[str], keywords: list[str],
                         allowed_ext: tuple[str, ...] = (".zip", ".xlsx", ".xls", ".csv", ".pdf", ".ods", ".json", ".xml", ".log"),
                         max_file_bytes: int = 750 * 1024 * 1024) -> None:
    all_links: list[dict[str, str]] = []
    for idx, page in enumerate(pages, start=1):
        save_text(lot, fonte, page, f"pagina_oficial_{idx:02d}.html",
                  observation="Página oficial preservada como evidência de descoberta")
        try:
            all_links.extend(extract_links(page))
        except Exception as exc:
            record_failure(lot, fonte, "INVENTARIO_LINKS", page, exc)
    # de-duplicate and save the complete discoverable link inventory
    dedup: dict[str, dict[str, str]] = {row["url"]: row for row in all_links}
    write_links(lot, "inventario_links_oficiais.csv", dedup.values())
    key_rx = re.compile("|".join(re.escape(k) for k in keywords), re.I) if keywords else None
    for row in dedup.values():
        u = row["url"]
        path_lower = urlparse(u).path.lower()
        text = (u + " " + row.get("texto", ""))
        if not path_lower.endswith(allowed_ext):
            continue
        if key_rx and not key_rx.search(text):
            continue
        download(lot, fonte, u, max_bytes=max_file_bytes,
                 observation="Arquivo descoberto em página oficial e filtrado pelo escopo semântico do lote")


def write_semantic_crosswalk() -> None:
    rows = [
        ["G5-L01", "F-013", "condição domiciliar observada", "domicílios/moradores", "Censo 2022", "núcleo", "correlacionar com SINISA sem equiparar oferta e resultado"],
        ["G5-L02", "F-014", "prestação, operação e gestão de saneamento", "município/prestador/serviço", "SINISA", "núcleo", "manter dimensão distinta do Censo"],
        ["G5-L03", "F-015", "resultado social e institucional complementar", "município/indicador/ano", "IMRS", "núcleo seletivo", "excluir duplicações de IDHM, IDSC, Censo, MUNIC e SICONFI"],
        ["G5-L04", "F-016", "capacidade fiscal e investimento urbano", "município/exercício/conta", "SICONFI", "núcleo", "fonte fiscal primária prevalece sobre indicador derivado"],
        ["G5-L05", "F-017", "evento histórico oficialmente registrado", "município/ocorrência/ano", "Atlas Digital", "núcleo", "não equiparar ocorrência a suscetibilidade física"],
        ["G5-L06", "F-018", "predisposição física mapeada", "município/polígono", "SGB", "contextual", "não mapeado não significa baixo risco"],
        ["G5-L07", "F-006", "condicionantes e contexto ambiental", "feição/município", "IDE-Sisema", "contextual", "limitar aos cinco grupos aprovados e controlar sobreposição"],
        ["G5-L08", "F-019", "pressão territorial minerária informativa", "processo/polígono/município", "SIGMINE", "contextual", "sem inferência de regularidade ou ilegalidade"],
        ["G5-L09", "F-020", "política e produção habitacional oficial", "município/empreendimento/unidade", "SNHIS/MCMV", "núcleo seletivo", "não denominar proxy como déficit habitacional"],
    ]
    path = ROOT / "correlacao_semantica_g5_l01_l09.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["lote_id", "fonte_id", "conceito_central", "unidade_observacao", "fonte", "classe", "regra_correlacao"])
        w.writerows(rows)


def collect_l01() -> None:
    lot, fonte = "G5-L01", "F-013"
    base = "https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/Agregados_por_Setor_csv/"
    save_text(lot, fonte, base, "indice_oficial_ibge.html")
    for fn in [
        "Agregados_por_setores_caracteristicas_domicilio2_BR_20250417.zip",
        "Agregados_por_setores_caracteristicas_domicilio3_BR_20250417.zip",
    ]:
        download(lot, fonte, base + fn, fn, observation="Módulo complementar nacional integral do Censo 2022")


def collect_l02() -> None:
    pages = [
        "https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/saneamento/sinisa/resultados-sinisa/resultados-sinisa",
        "https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/saneamento/sinisa/resultados-sinisa/arquivos",
    ]
    crawl_official_files("G5-L02", "F-014", pages,
        ["sinisa", "gestao", "gestão", "agua", "água", "esgoto", "esgotamento", "residuo", "resíduo", "pluvia", "glossario", "glossário", "atestado", "relatorio", "relatório"])


def collect_l03() -> None:
    lot, fonte = "G5-L03", "F-015"
    pages = [
        "https://imrs.fjp.mg.gov.br/",
        "https://imrs.fjp.mg.gov.br/Consultas",
        "https://imrs.fjp.mg.gov.br/Metodologia",
    ]
    # The full indicator values are intentionally not pulled before semantic selection.
    crawl_official_files(lot, fonte, pages,
        ["metod", "indicador", "dimens", "regional", "compos", "dicion", "fonte"],
        max_file_bytes=300 * 1024 * 1024)
    (ensure_lot(lot) / "MODO_AQUISICAO.txt").write_text(
        "CATALOGO_E_DOCUMENTACAO_INTEGRAIS. A exportacao CSV dos indicadores selecionados integra a etapa de snapshot, apos admissao semantica e controle de redundancia.\n",
        encoding="utf-8")


def collect_l04() -> None:
    lot, fonte = "G5-L04", "F-016"
    save_text(lot, fonte, "https://apidatalake.tesouro.gov.br/docs/siconfi/", "documentacao_api_siconfi.html")
    download(lot, fonte, "https://apidatalake.tesouro.gov.br/docs/siconfi.yaml", "siconfi_openapi_v1_1_0.yaml")
    save_text(lot, fonte, "https://www.tesourotransparente.gov.br/consultas/consultas-siconfi/siconfi-api-de-dados-abertos", "pagina_oficial_api_dados_abertos.html")
    save_text(lot, fonte, "https://siconfi.tesouro.gov.br/siconfi/pages/public/conteudo/conteudo.jsf?id=21903", "pagina_finbra_downloads.html")
    (ensure_lot(lot) / "MODO_AQUISICAO.txt").write_text(
        "ESPECIFICACAO E DOCUMENTACAO OFICIAIS INTEGRAIS. As consultas municipais paginadas dos exercicios selecionados serao congeladas na etapa de snapshot, respeitando o limite oficial de requisicoes.\n",
        encoding="utf-8")


def collect_l05() -> None:
    pages = ["https://atlasdigital.mdr.gov.br/paginas/downloads.xhtml"]
    crawl_official_files("G5-L05", "F-017", pages,
        ["atlas", "base", "dados", "manual", "correc", "log", "download"],
        max_file_bytes=1_500 * 1024 * 1024)


def collect_l06() -> None:
    lot, fonte = "G5-L06", "F-018"
    pages = [
        "https://www.sgb.gov.br/produtos-por-estado-cartografia-de-suscetibilidade",
        "https://www.sgb.gov.br/suscetibilidade-mg",
    ]
    links: list[dict[str, str]] = []
    for idx, page in enumerate(pages, start=1):
        save_text(lot, fonte, page, f"catalogo_oficial_{idx:02d}.html")
        try:
            links.extend(extract_links(page))
        except Exception as exc:
            record_failure(lot, fonte, "INVENTARIO_LINKS", page, exc)
    write_links(lot, "inventario_integral_produtos_mg.csv", {x["url"]: x for x in links}.values())
    (ensure_lot(lot) / "MODO_AQUISICAO.txt").write_text(
        "CATALOGO INTEGRAL DOS PRODUTOS MINEIROS. Os pacotes SIG/MDE individuais, potencialmente de grande volume, serao baixados e segmentados na etapa de snapshot. Nenhum municipio sem produto sera classificado como baixo risco.\n",
        encoding="utf-8")


def collect_l07() -> None:
    lot, fonte = "G5-L07", "F-006"
    pages = [
        "https://idesisema.meioambiente.mg.gov.br/geonetwork/srv/por/catalog.search",
        "https://idesisema.meioambiente.mg.gov.br/geonetwork/srv/por/catalog.search#/search?resultType=details&sortBy=relevance&from=1&to=20&fast=index",
        "https://idesisema.meioambiente.mg.gov.br/",
    ]
    for idx, page in enumerate(pages, start=1):
        save_text(lot, fonte, page, f"catalogo_geonetwork_{idx:02d}.html")
    for service, url in {
        "wms_getcapabilities.xml": "https://idesisema.meioambiente.mg.gov.br/geoserver/ows?service=WMS&request=GetCapabilities",
        "wfs_getcapabilities.xml": "https://idesisema.meioambiente.mg.gov.br/geoserver/ows?service=WFS&request=GetCapabilities",
        "wcs_getcapabilities.xml": "https://idesisema.meioambiente.mg.gov.br/geoserver/ows?service=WCS&request=GetCapabilities",
        "csw_getcapabilities.xml": "https://idesisema.meioambiente.mg.gov.br/geonetwork/srv/por/csw?service=CSW&request=GetCapabilities&version=2.0.2",
    }.items():
        download(lot, fonte, url, service, mode="CAPABILITIES_OFICIAL", required=False,
                 max_bytes=150 * 1024 * 1024)
    (ensure_lot(lot) / "MODO_AQUISICAO.txt").write_text(
        "CATALOGO, METADADOS E CAPABILITIES INTEGRAIS. A extracao das cinco familias tematicas aprovadas sera congelada na etapa de snapshot, com CRS, data e cobertura por camada.\n",
        encoding="utf-8")


def collect_l08() -> None:
    lot, fonte = "G5-L08", "F-019"
    root = "https://dadosabertos.anm.gov.br/SIGMINE/"
    save_text(lot, fonte, root, "indice_oficial_sigmine.html")
    download(lot, fonte, root + "PROCESSOS_MINERARIOS/MG.zip", "SIGMINE_PROCESSOS_MINERARIOS_MG.zip",
             observation="Recorte oficial integral de Minas Gerais")
    download(lot, fonte, root + "metadados-sigmine.ods", "metadados-sigmine.ods")
    try:
        links = extract_links(root)
        write_links(lot, "inventario_camadas_correlatas_sigmine.csv", links)
    except Exception as exc:
        record_failure(lot, fonte, "INVENTARIO_LINKS", root, exc)


def collect_l09() -> None:
    pages = [
        "https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/habitacao/programa-minha-casa-minha-vida/bases-de-dados-do-programa-minha-casa-minha-vida",
        "https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/habitacao/sistema-nacional-de-habitacao-de-interesse-social-snhis/regularidade-institucional",
    ]
    crawl_official_files("G5-L09", "F-020", pages,
        ["dados_abertos", "dados-abertos", "mcmv", "minha_casa", "minha-casa", "ogu", "fgts", "dicion", "snhis", "regularidade"],
        max_file_bytes=1_500 * 1024 * 1024)
    (ensure_lot("G5-L09") / "MODO_AQUISICAO.txt").write_text(
        "PACOTES PUBLICOS MCMV BAIXADOS QUANDO DISPONIVEIS E PAGINA OFICIAL SNHIS INVENTARIADA. A tabela dinamica de regularidade sera congelada na etapa de snapshot. E vedada a criacao de proxy denominado deficit habitacional municipal.\n",
        encoding="utf-8")


def finalize() -> None:
    write_semantic_crosswalk()
    with (ROOT / "manifesto_downloads.json").open("w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in records], f, ensure_ascii=False, indent=2)
    fields = list(asdict(records[0]).keys()) if records else [f.name for f in Record.__dataclass_fields__.values()]
    with (ROOT / "manifesto_downloads.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in records:
            w.writerow(asdict(r))
    with (ROOT / "erros_download.csv").open("w", newline="", encoding="utf-8-sig") as f:
        fields_e = ["lote_id", "fonte_id", "modalidade", "url", "erro", "mensagem", "observacao", "data_hora_utc"]
        w = csv.DictWriter(f, fieldnames=fields_e)
        w.writeheader()
        w.writerows(errors)
    summary = {
        "data_hora_utc": now_utc(),
        "total_registros": len(records),
        "baixados_ou_catalogados": sum(r.resultado in {"BAIXADO_INTEGRALMENTE", "CATALOGO_BAIXADO"} for r in records),
        "falhas": len(errors),
        "lotes": sorted({r.lote_id for r in records}),
        "regra": "arquivos estaticos integrais; fontes dinamicas/distribuidas catalogadas integralmente para snapshot temporal posterior",
    }
    (ROOT / "resumo_execucao.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "README_EXECUCAO.md").write_text(
        "# Aquisição oficial G5-L01 a G5-L09\n\n"
        "Esta execução separa aquisição de fonte e criação de snapshot. Arquivos oficiais estáticos foram baixados integralmente. "
        "Fontes dinâmicas, distribuídas ou geoespaciais de grande volume tiveram catálogos, metadados, links e capabilities preservados; "
        "a extração temporal e segmentação dos dados ocorrerá no estágio de snapshots.\n\n"
        "Nenhuma falha silenciosa é permitida. Consulte `manifesto_downloads.csv`, `erros_download.csv` e os arquivos `MODO_AQUISICAO.txt`.\n",
        encoding="utf-8")
    # Copy global governance files into each lot so every artifact is self-describing.
    for lot_dir in [p for p in ROOT.iterdir() if p.is_dir() and p.name.startswith("G5-L")]:
        for name in ["README_EXECUCAO.md", "manifesto_downloads.csv", "erros_download.csv", "correlacao_semantica_g5_l01_l09.csv"]:
            shutil.copy2(ROOT / name, lot_dir / name)


def main() -> None:
    collectors = [collect_l01, collect_l02, collect_l03, collect_l04, collect_l05, collect_l06, collect_l07, collect_l08, collect_l09]
    for fn in collectors:
        try:
            fn()
        except Exception as exc:
            lot = fn.__name__.replace("collect_l", "G5-L")
            record_failure(lot, "DESCONHECIDA", "EXECUCAO_LOTE", "", exc, "Falha não interrompe os demais lotes")
    finalize()
    print(json.dumps(json.loads((ROOT / "resumo_execucao.json").read_text(encoding="utf-8")), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
