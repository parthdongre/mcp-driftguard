from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .models import ChangeClass


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
        "real_benign_history",
        "controlled_benign",
        "synthetic_attack",
        "real_incident",
    ]
    attack_family: str | None = None
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


def read_pair_jsonl(path: str | Path) -> list[PairDatasetRecord]:
    records: list[PairDatasetRecord] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(PairDatasetRecord.model_validate(json.loads(line)))
    return records
