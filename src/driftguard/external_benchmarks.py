from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .dataset import PairDatasetRecord
from .models import ChangeClass


class ExternalVersionPair(BaseModel):
    """Neutral interchange format for independent MCP security datasets.

    Dataset-specific converters should emit this format. Keeping the core importer
    dataset-agnostic lets external attacks remain independent from DriftGuard's own
    synthetic generator and avoids hard-coding assumptions about one benchmark release.
    """

    source_dataset: str
    source_record_id: str
    repository_id: str
    server_id: str
    tool_name: str
    trusted_tool: dict[str, Any]
    candidate_tool: dict[str, Any]
    malicious: bool
    attack_family: str | None = None
    provenance_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def normalize_external_pair(record: ExternalVersionPair) -> PairDatasetRecord:
    label = ChangeClass.MALICIOUS_DRIFT if record.malicious else ChangeClass.BENIGN_MAINTENANCE
    provenance = "synthetic_attack" if record.malicious else "controlled_benign"
    notes = f"Imported from independent dataset {record.source_dataset}:{record.source_record_id}."
    if record.provenance_url:
        notes += f" Source: {record.provenance_url}"
    return PairDatasetRecord(
        record_id=f"external:{record.source_dataset}:{record.source_record_id}",
        repository_id=record.repository_id,
        server_id=record.server_id,
        tool_name=record.tool_name,
        old_tool=record.trusted_tool,
        new_tool=record.candidate_tool,
        label=label,
        provenance=provenance,
        attack_family=(
            f"external/{record.source_dataset}/{record.attack_family}"
            if record.malicious and record.attack_family
            else None
        ),
        notes=notes,
    )


def read_external_jsonl(path: str | Path) -> list[ExternalVersionPair]:
    records: list[ExternalVersionPair] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                records.append(ExternalVersionPair.model_validate(json.loads(line)))
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"Invalid external benchmark record at line {line_number}") from exc
    return records


def import_external_jsonl(path: str | Path) -> list[PairDatasetRecord]:
    """Normalize an independently sourced benchmark into DriftGuard pair records."""

    return [normalize_external_pair(record) for record in read_external_jsonl(path)]


def validate_external_independence(records: list[PairDatasetRecord]) -> None:
    """Reject common provenance mistakes before using external data for paper claims."""

    if not records:
        raise ValueError("External benchmark is empty")
    record_ids = [record.record_id for record in records]
    if len(record_ids) != len(set(record_ids)):
        raise ValueError("External benchmark contains duplicate normalized record IDs")
    if any(not record.record_id.startswith("external:") for record in records):
        raise ValueError("All records must retain external provenance in record_id")
    if any(record.old_tool == record.new_tool for record in records):
        raise ValueError("External version pairs must contain an actual tool-definition change")
