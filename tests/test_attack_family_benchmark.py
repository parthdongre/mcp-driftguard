from __future__ import annotations

import pytest

from driftguard.attack_family_benchmark import (
    MALICIOUS_ATTACK_FAMILIES,
    controlled_attack_family_folds,
    evaluate_attack_family_holdout,
)
from driftguard.bounded_drift import is_budgeted_rug_pull
from driftguard.models import ChangeClass
from driftguard.trajectory_benchmark import TemporalStrategy


def test_attack_family_folds_are_repository_and_family_disjoint() -> None:
    folds = controlled_attack_family_folds()
    assert {fold.held_out_family for fold in folds} == set(MALICIOUS_ATTACK_FAMILIES)

    for fold in folds:
        validation_repositories = {item.repository_id for item in fold.validation}
        test_repositories = {item.repository_id for item in fold.test}
        assert validation_repositories.isdisjoint(test_repositories)

        validation_families = {
            step.attack_family
            for item in fold.validation
            for step in item.steps
            if step.attack_family is not None
        }
        assert fold.held_out_family not in validation_families

        test_malicious = [
            item for item in fold.test if item.final_label is ChangeClass.MALICIOUS_DRIFT
        ]
        test_families = {
            step.attack_family
            for item in test_malicious
            for step in item.steps
            if step.attack_family is not None
        }
        assert test_families == {fold.held_out_family}


def test_held_out_c3_trajectories_are_genuinely_bounded() -> None:
    for fold in controlled_attack_family_folds():
        malicious = [
            item for item in fold.test if item.final_label is ChangeClass.MALICIOUS_DRIFT
        ]
        assert malicious
        assert all(is_budgeted_rug_pull(item) for item in malicious)


def test_family_holdout_evaluates_every_temporal_strategy() -> None:
    for fold in controlled_attack_family_folds():
        evaluations = evaluate_attack_family_holdout(fold)
        assert {item.strategy for item in evaluations} == set(TemporalStrategy)
        for item in evaluations:
            strict = item.strict_unseen_family_metrics
            assert strict.held_out_family == fold.held_out_family
            assert strict.malicious_traces > 0
            assert 0.0 <= strict.post_onset_block_rate <= 1.0
            assert 0.0 <= strict.pre_onset_block_rate <= 1.0
            assert strict.budgeted_rug_pull_rate == pytest.approx(1.0)
            assert 0.0 <= item.selection.thresholds.block_threshold <= 1.0
            assert 0.0 <= item.selection.thresholds.reconsent_threshold <= 1.0
