from __future__ import annotations

from driftguard.consent_policy import (
    ConsentPolicyThresholds,
    SequenceRiskTrace,
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
