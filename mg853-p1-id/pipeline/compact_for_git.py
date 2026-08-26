from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path('mg853-p1-id/data')
RAW = ROOT / 'raw' / 'current'
NORM = ROOT / 'normalized'
META = ROOT / 'metadata'
HIST = ROOT / 'history'
PERSISTENCE_POLICY_VERSION = '1.0'


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def gzip_deterministic(path: Path) -> Path:
    target = path.with_name(path.name + '.gz')
    raw = path.read_bytes()
    target.write_bytes(gzip.compress(raw, compresslevel=9, mtime=0))
    path.unlink()
    return target


def compact_raw() -> None:
    manifest_path = META / 'raw_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    for item in manifest:
        source = ROOT / item['arquivo']
        if not source.exists():
            continue
        original_sha = item.pop('sha256', sha256(source))
        original_bytes = item.pop('bytes', source.stat().st_size)
        compressed = gzip_deterministic(source)
        item.update({
            'arquivo': str(compressed.relative_to(ROOT)),
            'sha256_fonte_bruta': original_sha,
            'bytes_fonte_bruta': original_bytes,
            'sha256_arquivo_gzip': sha256(compressed),
            'bytes_arquivo_gzip': compressed.stat().st_size,
            'compressao': 'gzip; compresslevel=9; mtime=0',
        })
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')


def compact_lossless_wide() -> None:
    source = NORM / 'idsc_brasil_municipios_source_wide.csv'
    if not source.exists():
        return
    target = source.with_name(source.name + '.gz')
    frame = pd.read_csv(source, low_memory=False)
    frame.to_csv(
        target,
        index=False,
        encoding='utf-8-sig',
        compression={'method': 'gzip', 'compresslevel': 9, 'mtime': 0},
    )
    source.unlink()


def compact_national_ods() -> None:
    source = NORM / 'idsc_brasil_ods_long.csv'
    if not source.exists():
        return
    frame = pd.read_csv(source, low_memory=False)
    # O payload textual extenso já está preservado integralmente nas camadas
    # raw gzip e source-wide lossless; aqui permanece a tabela analítica normalizada.
    frame = frame.drop(columns=['payload_ods_json'], errors='ignore')
    frame.to_csv(source, index=False, encoding='utf-8-sig')


def rebuild_dataset_manifest() -> None:
    manifest_path = META / 'dataset_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    files = []
    for path in sorted(ROOT.rglob('*')):
        if not path.is_file() or 'history' in path.parts or path.name == 'dataset_manifest.json':
            continue
        files.append({
            'arquivo': str(path.relative_to(ROOT)),
            'sha256': sha256(path),
            'bytes': path.stat().st_size,
        })
    manifest['arquivos'] = files
    manifest['persistencia_git'] = {
        'policy_version': PERSISTENCE_POLICY_VERSION,
        'raw': 'gzip determinístico, conteúdo integral',
        'source_wide': 'CSV gzip determinístico, camada lossless',
        'ods_nacional': 'CSV normalizado sem duplicação do payload textual; conteúdo integral preservado nas camadas raw/source-wide',
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    snapshot_date = manifest['snapshot_date']
    snapshot = HIST / snapshot_date / 'manifest_snapshot.json'
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')


def assert_size_policy() -> None:
    hard_limit = 100 * 1024 * 1024
    oversized = [(str(p), p.stat().st_size) for p in ROOT.rglob('*') if p.is_file() and p.stat().st_size >= hard_limit]
    if oversized:
        raise RuntimeError(f'Arquivos acima do limite GitHub: {oversized}')


def main() -> None:
    compact_raw()
    compact_lossless_wide()
    compact_national_ods()
    rebuild_dataset_manifest()
    assert_size_policy()
    print(json.dumps({
        'status': 'COMPACTACAO_APROVADA',
        'policy_version': PERSISTENCE_POLICY_VERSION,
        'arquivos': len([p for p in ROOT.rglob('*') if p.is_file()]),
        'maior_arquivo_bytes': max((p.stat().st_size for p in ROOT.rglob('*') if p.is_file()), default=0),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
