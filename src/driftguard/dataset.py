from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .models import ChangeClass


class AnnotationCandidate(BaseModel):
    """Unlabeled real-history transition awaiting independent human review."""

    candidate_id: str
    repository_id: str
    server_id: str
    tool_name: str
    source_path: str
    old_version_id: str
    new_version_id: str
    old_committed_at: str | None = None
    new_committed_at: str | None = None
    old_tool: dict[str, Any]
    new_tool: dict[str, Any]
    provenance: Literal["real_history"] = "real_history"
    suggested_evidence: list[str] = Field(default_factory=list)
    notes: str | None = None

    @property
    def leakage_group(self) -> str:
        return self.repository_id


class PairDatasetRecord(BaseModel):
    """Canonical record for one supervised old/new tool-definition example."""

    record_id: str
    repository_id: str
    server_id: str
    tool_name: str
    old_tool: dict[str, Any]
    new_tool: dict[str, Any]
    label: ChangeClass
    provenance: Literal[
        "real_history",
        "real_benign_history",
        "controlled_benign",
        "synthetic_attack",
        "real_incident",
    ]
    attack_family: str | None = None
    old_version_id: str | None = None
    new_version_id: str | None = None
    old_committed_at: str | None = None
    new_committed_at: str | None = None
    annotators: list[str] = Field(default_factory=list)
    notes: str | None = None

    @property
    def leakage_group(self) -> str:
        """Repository-level split key used to prevent near-duplicate train/test leakage."""

        return self.repository_id


class TrajectoryStep(BaseModel):
    version_id: str
    tool: dict[str, Any]
    transition_label: ChangeClass | None = None
    attack_family: str | None = None


class TrajectoryDatasetRecord(BaseModel):
    """Sequence record for low-and-slow and trust-decay experiments."""

    trajectory_id: str
    repository_id: str
    server_id: str
    tool_name: str
    approved_version_id: str
    steps: list[TrajectoryStep] = Field(min_length=2)
    final_label: ChangeClass
    provenance: str
    notes: str | None = None

    @property
    def leakage_group(self) -> str:
        return self.repository_id


def write_jsonl(path: str | Path, records: list[BaseModel]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(record.model_dump_json() + "\n")


def _read_jsonl(path: str | Path, model_type: type[BaseModel]) -> list[BaseModel]:
    records: list[BaseModel] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(model_type.model_validate(json.loads(line)))
    return records


def read_pair_jsonl(path: str | Path) -> list[PairDatasetRecord]:
    return [
        record
        for record in _read_jsonl(path, PairDatasetRecord)
        if isinstance(record, PairDatasetRecord)
    ]


def read_candidate_jsonl(path: str | Path) -> list[AnnotationCandidate]:
    return [
        record
        for record in _read_jsonl(path, AnnotationCandidate)
        if isinstance(record, AnnotationCandidate)
    ]


def read_trajectory_jsonl(path: str | Path) -> list[TrajectoryDatasetRecord]:
    return [
        record
        for record in _read_jsonl(path, TrajectoryDatasetRecord)
        if isinstance(record, TrajectoryDatasetRecord)
    ]
