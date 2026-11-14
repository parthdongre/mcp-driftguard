from __future__ import annotations

import pytest

pytest.importorskip("sklearn")

from driftguard.attack_family_benchmark import controlled_attack_family_folds
from driftguard.learned_family_benchmark import (
    evaluate_learned_family_fold,
    split_attack_family_fold,
    trajectory_training_pairs,
)
from driftguard.models import ChangeClass


def test_learned_fold_has_three_repository_disjoint_partitions() -> None:
    for fold in controlled_attack_family_folds():
        split = split_attack_family_fold(fold)
        train = {item.repository_id for item in split.train}
        policy = {item.repository_id for item in split.policy_validation}
        test = {item.repository_id for item in split.test}

        assert len(train) == 2
        assert len(policy) == 1
        assert len(test) == 3
        assert train.isdisjoint(policy)
        assert train.isdisjoint(test)
        assert policy.isdisjoint(test)

        seen_families = {
            step.attack_family
            for item in split.train + split.policy_validation
            for step in item.steps
            if step.attack_family is not None
        }
        assert fold.held_out_family not in seen_families


def test_training_pairs_cover_all_four_change_classes() -> None:
    fold = controlled_attack_family_folds()[0]
    split = split_attack_family_fold(fold)
    labels = {
        record.label
        for trajectory in split.train
        for record in trajectory_training_pairs(trajectory)
    }
    assert labels == set(ChangeClass)


def test_learned_family_benchmark_runs_without_repository_or_family_leakage() -> None:
    fold = controlled_attack_family_folds()[0]
    result = evaluate_learned_family_fold(fold)

    assert result.held_out_family == fold.held_out_family
    assert set(result.train_repositories).isdisjoint(result.policy_validation_repositories)
    assert set(result.train_repositories).isdisjoint(result.test_repositories)
    assert set(result.policy_validation_repositories).isdisjoint(result.test_repositories)
    assert result.pair_metrics.records > 0
    assert 0.0 <= result.pair_metrics.macro_f1 <= 1.0
    assert result.pair_metrics.malicious_auroc is None or (
        0.0 <= result.pair_metrics.malicious_auroc <= 1.0
    )
    assert len(result.strategies) == 3


def test_multiclass_macro_f1_ignores_classes_absent_from_truth_and_predictions() -> None:
    from driftguard.evaluation import multiclass_metrics

    labels = [ChangeClass.BENIGN_MAINTENANCE, ChangeClass.MALICIOUS_DRIFT]
    assert multiclass_metrics(labels, labels)["macro_f1"] == 1.0


def test_prepared_trajectory_starts_at_approved_version() -> None:
    from driftguard.dataset import TrajectoryDatasetRecord, TrajectoryStep
    from driftguard.learned_family_benchmark import prepare_learned_trajectory

    class StubModel:
        def predict_proba(self, record):
            return {"C3": 1.0 if record.new_version_id == "v3" else 0.0}

    tool = {"name": "t", "description": "Search."}
    trajectory = TrajectoryDatasetRecord(
        trajectory_id="t",
        repository_id="r",
        server_id="s",
        tool_name="t",
        approved_version_id="v1",
        steps=[
            TrajectoryStep(version_id=f"v{index}", tool={**tool, "description": f"v{index}"})
            for index in range(3)
        ]
        + [
            TrajectoryStep(
                version_id="v3",
                tool={**tool, "description": "v3"},
                transition_label=ChangeClass.MALICIOUS_DRIFT,
                attack_family="x",
            )
        ],
        final_label=ChangeClass.MALICIOUS_DRIFT,
        provenance="test",
    )
    prepared = prepare_learned_trajectory(StubModel(), trajectory)

    assert prepared.version_ids == ("v2", "v3")
    assert prepared.attack_onset == 1
    assert prepared.pair_probabilities[(0, 2)]["C3"] == 1.0
    assert set(prepared.pair_probabilities) == {(0, 1), (0, 2), (1, 2)}
