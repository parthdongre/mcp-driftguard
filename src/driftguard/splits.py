from __future__ import annotations

import json
from collections.abc import Iterable
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
