from __future__ import annotations

import pytest

from driftguard.consent_policy import (
    ConsentPolicyThresholds,
    SequenceRiskTrace,
    consent_security_pareto_frontier,
    evaluate_consent_policy,
    select_consent_policy,
)
from driftguard.models import ChangeClass


def _traces() -> list[SequenceRiskTrace]:
    return [
        SequenceRiskTrace(
            trace_id="benign-1",
            final_label=ChangeClass.BENIGN_MAINTENANCE,
            malicious_scores=(0.02, 0.03, 0.04),
            capability_scores=(0.02, 0.04, 0.05),
        ),
        SequenceRiskTrace(
            trace_id="benign-2",
            final_label=ChangeClass.NO_MEANINGFUL_CHANGE,
            malicious_scores=(0.01, 0.01),
            capability_scores=(0.01, 0.01),
        ),
        SequenceRiskTrace(
            trace_id="c2",
            final_label=ChangeClass.CAPABILITY_EXPANSION,
            malicious_scores=(0.04, 0.08, 0.10),
            capability_scores=(0.10, 0.30, 0.62),
        ),
        SequenceRiskTrace(
            trace_id="attack-1",
            final_label=ChangeClass.MALICIOUS_DRIFT,
            malicious_scores=(0.05, 0.22, 0.72),
            capability_scores=(0.08, 0.20, 0.55),
            attack_onset=1,
        ),
        SequenceRiskTrace(
            trace_id="attack-2",
            final_label=ChangeClass.MALICIOUS_DRIFT,
            malicious_scores=(0.03, 0.61, 0.80),
            capability_scores=(0.04, 0.18, 0.50),
            attack_onset=1,
        ),
    ]


def test_consent_policy_separates_benign_c2_and_attacks() -> None:
    metrics = evaluate_consent_policy(
        _traces(),
        ConsentPolicyThresholds(reconsent_threshold=0.50, block_threshold=0.55),
    )
    assert metrics.malicious_detection_rate == 1.0
    assert metrics.malicious_block_rate == 1.0
    assert metrics.c2_reconsent_rate == 1.0
    assert metrics.benign_reconsent_rate == 0.0
    assert metrics.benign_block_rate == 0.0


def test_policy_selection_uses_security_constraints() -> None:
    selected = select_consent_policy(
        _traces(),
        reconsent_grid=(0.40, 0.50, 0.60),
        block_grid=(0.50, 0.55, 0.65),
        min_malicious_detection=1.0,
        max_benign_block_rate=0.0,
        max_benign_reconsent_rate=0.0,
    )
    assert selected.feasible
    assert selected.metrics.malicious_detection_rate == 1.0
    assert selected.metrics.benign_block_rate == 0.0


def test_pareto_frontier_contains_only_non_dominated_points() -> None:
    frontier = consent_security_pareto_frontier(
        _traces(),
        reconsent_grid=(0.30, 0.50, 0.70),
        block_grid=(0.45, 0.55, 0.75),
    )
    assert frontier
    assert any(item.metrics.malicious_detection_rate == 1.0 for item in frontier)
    thresholds = {item.thresholds for item in frontier}
    assert len(thresholds) == len(frontier)


def test_pre_onset_intervention_is_not_credited_as_attack_detection() -> None:
    trace = SequenceRiskTrace(
        trace_id="early-only",
        final_label=ChangeClass.MALICIOUS_DRIFT,
        malicious_scores=(0.9, 0.0, 0.0),
        capability_scores=(0.0, 0.0, 0.0),
        attack_onset=2,
    )
    metrics = evaluate_consent_policy([trace], ConsentPolicyThresholds(0.5, 0.5))
    assert metrics.malicious_detection_rate == 0.0
    assert metrics.malicious_block_rate == 0.0
    assert metrics.mean_detection_delay is None
    assert metrics.pre_onset_intervention_rate == 1.0


def test_duplicate_trace_ids_cannot_overwrite_policy_outcomes() -> None:
    with pytest.raises(ValueError, match="unique"):
        evaluate_consent_policy([_traces()[0], _traces()[0]], ConsentPolicyThresholds(0.5, 0.5))


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -0.1, 1.1])
def test_policy_trace_rejects_invalid_scores(score: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        SequenceRiskTrace("bad", ChangeClass.BENIGN_MAINTENANCE, (score,), (0.0,))


def test_policy_selection_rejects_empty_grid() -> None:
    with pytest.raises(ValueError, match="grids"):
        select_consent_policy(_traces(), block_grid=())
