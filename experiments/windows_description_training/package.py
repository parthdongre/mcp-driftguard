#!/usr/bin/env python3
"""Create and verify the local Windows-training handoff archive."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts" / "windows-mcp-description-training"
ARCHIVE = OUT / "driftguard-windows-training.zip"
EXPERIMENT = ROOT / "experiments" / "windows_description_training"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def files_under(path: Path) -> Iterable[Path]:
    for file in sorted(path.rglob("*")):
        if file.is_file() and "__pycache__" not in file.parts:
            yield file


def selected_files() -> list[Path]:
    required = [
        OUT / "data" / "pairs.jsonl",
        OUT / "data" / "split_manifest.json",
        OUT / "data" / "split_index.json",
        OUT / "data" / "source_manifest.json",
        OUT / "data" / "blinded_review_queue.jsonl",
        OUT / "data" / "time_challenge.jsonl",
        OUT / "data" / "unresolved_history_candidates.jsonl",
        OUT / "data" / "capgate_external_manifest.json",
        OUT / "run" / "run_config.json",
        OUT / "run" / "dependency-lock.txt",
        OUT / "run" / "smoke_result.json",
        OUT / "run" / "epoch_metrics.json",
        OUT / "run" / "validation_thresholds.json",
        OUT / "metrics.json",
        OUT / "README_handoff.md",
        ROOT / "src" / "mcp_driftguard" / "heuristics.py",
    ]
    for path in required:
        if not path.exists():
            raise FileNotFoundError(f"cannot package incomplete run; missing {path}")
    selected = set(required)
    selected.update(files_under(EXPERIMENT))
    selected.update(files_under(OUT / "predictions"))
    selected.update(files_under(OUT / "analysis"))
    selected.update(files_under(OUT / "run" / "logs"))
    selected.update(files_under(OUT / "models" / "best"))
    selected.add(OUT / "models" / "tfidf_logistic.joblib")
    for epoch_dir in sorted((OUT / "models").glob("epoch-*")):
        selected.update(files_under(epoch_dir))
    for name in ("histor-2026-11-16-manifest.json", "servers.jsonl.gz", "changes.jsonl.gz"):
        path = OUT / "source_cache" / name
        if not path.exists():
            raise FileNotFoundError(f"missing reproducible HISTOR source file: {path}")
        selected.add(path)
    # The external benchmark's record text is kept in the local cache, excluded
    # from this portable bundle because source-level rights vary.
    return sorted(path for path in selected if path.is_file())


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    run_config = json.loads((OUT / "run" / "run_config.json").read_text(encoding="utf-8"))
    source_manifest = json.loads((OUT / "data" / "source_manifest.json").read_text(encoding="utf-8"))
    handoff = f"""# DriftGuard Windows training handoff

## Status

Research only. The internal validation and test labels are provisional weak and controlled fictional labels. No independent human annotation file was available. The CAPGATE real-history subset is reported separately as rule-derived external diagnostics.

## Reproduction

From the repository root in PowerShell:

```powershell
`$python = ".\\.venv\\Scripts\\python.exe"
& `$python experiments\\windows_description_training\\prepare.py --offline
& `$python experiments\\windows_description_training\\train.py --smoke --revision {run_config['model_revision']}
& `$python experiments\\windows_description_training\\train.py --revision {run_config['model_revision']}
& `$python experiments\\windows_description_training\\evaluate.py
& `$python experiments\\windows_description_training\\package.py
```

Exact run settings are in `artifacts/windows-mcp-description-training/run/run_config.json`; exact resolved packages are in `run/dependency-lock.txt`. The source snapshot is HISTOR {source_manifest['snapshot_date']} ({source_manifest['license']}); the manifest and named gzip files were hash-verified before extraction.

## Results

See `metrics.json`, `predictions/`, and `analysis/`. The model was selected on the provisional validation split, and thresholds were selected on validation only. The model remains offline and was not installed in the live DriftGuard gateway.

## Rights and external data

The ZIP includes HISTOR's CC-BY-4.0 source files and per-record repository attribution. The raw CAPGATE JSON with third-party description text stays in the local cache. `data/capgate_external_manifest.json` records its pinned source revision, dataset hash, IDs, labels, and description hashes for reproducibility.
"""
    (OUT / "README_handoff.md").write_text(handoff, encoding="utf-8")
    source_paths = selected_files()
    entries = []
    with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=5, allowZip64=True) as archive:
        for path in source_paths:
            name = path.relative_to(ROOT).as_posix()
            archive.write(path, name)
            entries.append({"path": name, "bytes": path.stat().st_size, "sha256": sha256(path)})
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "archive": ARCHIVE.name,
            "entries": entries,
            "excluded": ["artifacts/windows-mcp-description-training/source_cache/capgate_dataset.json: rights vary by originating repository; see data/capgate_external_manifest.json"],
            "onnx_export": "not produced",
        }
        archive.writestr("bundle_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    with zipfile.ZipFile(ARCHIVE, "r") as archive:
        corrupt = archive.testzip()
        if corrupt:
            raise RuntimeError(f"ZIP CRC verification failed at {corrupt}")
        archived_manifest = json.loads(archive.read("bundle_manifest.json"))
        hash_failures = []
        for entry in archived_manifest["entries"]:
            actual = hashlib.sha256(archive.read(entry["path"])).hexdigest()
            if actual != entry["sha256"]:
                hash_failures.append(entry["path"])
        if hash_failures:
            raise RuntimeError(f"bundle entry hash mismatch: {hash_failures[:10]}")
    result = {
        "archive": str(ARCHIVE),
        "archive_bytes": ARCHIVE.stat().st_size,
        "archive_sha256": sha256(ARCHIVE),
        "entries_verified": len(entries),
        "zip_testzip": "passed",
        "entry_hashes": "passed",
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    (OUT / "archive_integrity.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
