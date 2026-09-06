import pytest

from driftguard.dataset import PairDatasetRecord
from driftguard.models import ChangeClass
from driftguard.splits import (
    SplitManifest,
    apply_split_manifest,
    build_split_manifest,
    held_out_family_test_records,
)


def tool(name):
    return {
        "name": name,
        "description": f"Tool {name}",
        "inputSchema": {"type": "object", "properties": {}},
    }


def record(index, repository, attack_family=None):
    return PairDatasetRecord(
        record_id=f"r-{index}",
        repository_id=repository,
        server_id=repository,
        tool_name="search",
        old_tool=tool("search"),
        new_tool=tool("search"),
        label=(
            ChangeClass.MALICIOUS_DRIFT
            if attack_family is not None
            else ChangeClass.BENIGN_MAINTENANCE
        ),
        provenance="synthetic_attack" if attack_family else "controlled_benign",
        attack_family=attack_family,
    )


def test_manifest_is_deterministic_and_repository_disjoint():
    records = [record(i, f"owner/repo-{i}") for i in range(10)]
    first = build_split_manifest(records, seed=7)
    second = build_split_manifest(records, seed=7)

    assert first == second
    assert not set(first.train_repositories) & set(first.validation_repositories)
    assert not set(first.train_repositories) & set(first.test_repositories)
    assert not set(first.validation_repositories) & set(first.test_repositories)
    assert first.repositories == {f"owner/repo-{i}" for i in range(10)}


def test_manifest_rejects_overlapping_repositories():
    with pytest.raises(ValueError, match="disjoint"):
        SplitManifest(
            train_repositories=["owner/repo"],
            validation_repositories=["owner/repo"],
        )


def test_held_out_family_never_enters_training():
    records = [
        record(1, "repo-train", "prompt_injection"),
        record(2, "repo-train", "data_exfiltration"),
        record(3, "repo-test", "prompt_injection"),
        record(4, "repo-test", "data_exfiltration"),
    ]
    manifest = SplitManifest(
        train_repositories=["repo-train"],
        test_repositories=["repo-test"],
        held_out_attack_families=["prompt_injection"],
    )
    split = apply_split_manifest(records, manifest)

    assert {item.attack_family for item in split.train} == {"data_exfiltration"}
    assert len(split.test) == 2
    held_out = held_out_family_test_records(records, manifest)
    assert len(held_out) == 1
    assert held_out[0].attack_family == "prompt_injection"


def test_strict_manifest_rejects_unassigned_repository():
    records = [record(1, "known"), record(2, "unknown")]
    manifest = SplitManifest(train_repositories=["known"])
    with pytest.raises(ValueError, match="absent"):
        apply_split_manifest(records, manifest, strict=True)
