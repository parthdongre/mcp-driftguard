from __future__ import annotations

import pytest

from driftguard.attack_family_benchmark import (
    MALICIOUS_ATTACK_FAMILIES,
    controlled_attack_family_folds,
    evaluate_attack_family_holdout,
)
from driftguard.attack_family_stateful import evaluate_stateful_attack_family_holdout
from driftguard.bounded_drift import is_budgeted_rug_pull
from driftguard.consent_policy import ConsentPolicyThresholds, PolicyAction
from driftguard.models import ChangeClass
from driftguard.stateful_policy import simulate_stateful_policy
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


def test_stateful_policy_resets_after_c2_reconsent() -> None:
    fold = next(
        item
        for item in controlled_attack_family_folds()
        if item.held_out_family == "prompt_injection"
    )
    trajectory = next(
        item for item in fold.test if item.final_label is ChangeClass.MALICIOUS_DRIFT
    )
    outcome = simulate_stateful_policy(
        trajectory,
        TemporalStrategy.APPROVED_BASELINE,
        ConsentPolicyThresholds(reconsent_threshold=0.10, block_threshold=0.30),
    )

    assert outcome.attack_onset is not None
    assert any(
        event.action is PolicyAction.RECONSENT
        and event.observation_index < outcome.attack_onset
        for event in outcome.events
    )
    assert not any(
        event.action is PolicyAction.BLOCK
        and event.observation_index < outcome.attack_onset
        for event in outcome.events
    )


def test_stateful_family_holdout_uses_validation_only_threshold_selection() -> None:
    for fold in controlled_attack_family_folds():
        evaluations = evaluate_stateful_attack_family_holdout(fold)
        assert {item.strategy for item in evaluations} == set(TemporalStrategy)
        for item in evaluations:
            assert item.held_out_family == fold.held_out_family
            assert item.selection.metrics.traces == len(fold.validation)
            assert item.test_metrics.traces == len(fold.test)
            assert 0.0 <= item.test_metrics.malicious_post_onset_block_rate <= 1.0
            assert 0.0 <= item.test_metrics.malicious_pre_onset_block_rate <= 1.0
            assert 0.0 <= item.test_metrics.benign_intervention_rate <= 1.0
