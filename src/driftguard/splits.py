from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from random import Random

from pydantic import BaseModel, Field, model_validator

from .dataset import PairDatasetRecord
from .learning import GroupedSplit


class SplitManifest(BaseModel):
    """Frozen repository-disjoint experiment partition.

    Once a paper experiment starts, this manifest should be versioned with the
    experiment artifacts so all baselines and proposed models use identical groups.
    """

    seed: int = 42
    train_repositories: list[str] = Field(default_factory=list)
    validation_repositories: list[str] = Field(default_factory=list)
    test_repositories: list[str] = Field(default_factory=list)
    held_out_attack_families: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_disjoint(self) -> SplitManifest:
        train = set(self.train_repositories)
        validation = set(self.validation_repositories)
        test = set(self.test_repositories)
        if train & validation or train & test or validation & test:
            raise ValueError("Repository partitions in a split manifest must be disjoint")
        return self

    @property
    def repositories(self) -> set[str]:
        return {
            *self.train_repositories,
            *self.validation_repositories,
            *self.test_repositories,
        }


class TemporalCutoffManifest(BaseModel):
    """Frozen chronological split for future-version generalization experiments."""

    validation_start: str
    test_start: str

    @model_validator(mode="after")
    def validate_order(self) -> TemporalCutoffManifest:
        validation = _parse_timestamp(self.validation_start)
        test = _parse_timestamp(self.test_start)
        if validation >= test:
            raise ValueError("validation_start must be earlier than test_start")
        return self


def _parse_timestamp(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO-8601 timestamp: {value}") from exc


def build_split_manifest(
    records: Iterable[PairDatasetRecord],
    *,
    train_fraction: float = 0.70,
    validation_fraction: float = 0.15,
    seed: int = 42,
    held_out_attack_families: Iterable[str] = (),
) -> SplitManifest:
    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must be between 0 and 1")
    if not 0 <= validation_fraction < 1:
        raise ValueError("validation_fraction must be between 0 and 1")
    if train_fraction + validation_fraction >= 1:
        raise ValueError("train + validation fractions must leave room for a test split")

    repositories = sorted({record.repository_id for record in records})
    Random(seed).shuffle(repositories)
    train_end = int(len(repositories) * train_fraction)
    validation_end = train_end + int(len(repositories) * validation_fraction)
    return SplitManifest(
        seed=seed,
        train_repositories=sorted(repositories[:train_end]),
        validation_repositories=sorted(repositories[train_end:validation_end]),
        test_repositories=sorted(repositories[validation_end:]),
        held_out_attack_families=sorted(set(held_out_attack_families)),
    )


def apply_split_manifest(
    records: Iterable[PairDatasetRecord],
    manifest: SplitManifest,
    *,
    strict: bool = True,
) -> GroupedSplit:
    records = list(records)
    if strict:
        unknown = {record.repository_id for record in records} - manifest.repositories
        if unknown:
            raise ValueError(
                "Records contain repositories absent from the frozen split manifest: "
                + ", ".join(sorted(unknown))
            )

    train_repositories = set(manifest.train_repositories)
    validation_repositories = set(manifest.validation_repositories)
    test_repositories = set(manifest.test_repositories)
    held_out = set(manifest.held_out_attack_families)

    def eligible_for_training(record: PairDatasetRecord) -> bool:
        return record.attack_family not in held_out

    return GroupedSplit(
        train=[
            record
            for record in records
            if record.repository_id in train_repositories and eligible_for_training(record)
        ],
        validation=[
            record
            for record in records
            if record.repository_id in validation_repositories and eligible_for_training(record)
        ],
        test=[record for record in records if record.repository_id in test_repositories],
    )


def apply_temporal_cutoff_manifest(
    records: Iterable[PairDatasetRecord],
    manifest: TemporalCutoffManifest,
    *,
    require_all_timestamps: bool = True,
) -> GroupedSplit:
    """Chronologically split reviewed pairs by the new-version commit timestamp.

    This is a separate evaluation regime from repository-disjoint testing. Its purpose is
    to measure future-version generalization. Paper experiments should report both rather
    than presenting this chronological split as repository-independent evidence.
    """

    validation_start = _parse_timestamp(manifest.validation_start)
    test_start = _parse_timestamp(manifest.test_start)
    train: list[PairDatasetRecord] = []
    validation: list[PairDatasetRecord] = []
    test: list[PairDatasetRecord] = []

    for record in records:
        if not record.new_committed_at:
            if require_all_timestamps:
                raise ValueError(
                    f"Record {record.record_id} lacks new_committed_at required for temporal split"
                )
            continue
        timestamp = _parse_timestamp(record.new_committed_at)
        if timestamp < validation_start:
            train.append(record)
        elif timestamp < test_start:
            validation.append(record)
        else:
            test.append(record)

    return GroupedSplit(train=train, validation=validation, test=test)


def held_out_family_test_records(
    records: Iterable[PairDatasetRecord], manifest: SplitManifest
) -> list[PairDatasetRecord]:
    families = set(manifest.held_out_attack_families)
    test_repositories = set(manifest.test_repositories)
    return [
        record
        for record in records
        if record.repository_id in test_repositories and record.attack_family in families
    ]


def write_split_manifest(path: str | Path, manifest: SplitManifest) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")


def read_split_manifest(path: str | Path) -> SplitManifest:
    return SplitManifest.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
