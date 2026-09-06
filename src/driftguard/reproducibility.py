from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FileEvidence:
    path: str
    sha256: str
    bytes: int


@dataclass(frozen=True)
class ExperimentManifest:
    experiment_name: str
    git_commit: str
    command: str
    seed: int | None
    thresholds: dict[str, float]
    files: tuple[FileEvidence, ...]
    model_identifiers: tuple[str, ...]
    python_version: str
    platform: str
    metadata: dict[str, Any]


def sha256_file(path: str | Path) -> FileEvidence:
    source = Path(path)
    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return FileEvidence(path=str(source), sha256=digest.hexdigest(), bytes=size)


def build_experiment_manifest(
    *,
    experiment_name: str,
    git_commit: str,
    command: str,
    evidence_files: list[str | Path],
    seed: int | None = None,
    thresholds: dict[str, float] | None = None,
    model_identifiers: tuple[str, ...] = (),
    metadata: dict[str, Any] | None = None,
) -> ExperimentManifest:
    if not git_commit.strip():
        raise ValueError("git_commit is required")
    if not command.strip():
        raise ValueError("command is required")
    files = tuple(sha256_file(path) for path in evidence_files)
    return ExperimentManifest(
        experiment_name=experiment_name,
        git_commit=git_commit,
        command=command,
        seed=seed,
        thresholds=dict(thresholds or {}),
        files=files,
        model_identifiers=tuple(model_identifiers),
        python_version=platform.python_version(),
        platform=platform.platform(),
        metadata=dict(metadata or {}),
    )


def write_experiment_manifest(path: str | Path, manifest: ExperimentManifest) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(asdict(manifest), indent=2, sort_keys=True), encoding="utf-8")


def verify_experiment_manifest(manifest: ExperimentManifest) -> list[str]:
    """Return evidence files whose current bytes no longer match the frozen manifest."""

    mismatches: list[str] = []
    for evidence in manifest.files:
        current = sha256_file(evidence.path)
        if current.sha256 != evidence.sha256 or current.bytes != evidence.bytes:
            mismatches.append(evidence.path)
    return mismatches
