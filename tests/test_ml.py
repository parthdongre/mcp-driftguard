from pathlib import Path

import pytest

from driftguard.canonicalize import make_snapshot
from driftguard.diff import build_delta
from driftguard.evaluation import load_jsonl
from driftguard.ml import PairwiseLogisticDetector

ROOT = Path(__file__).resolve().parents[1]


def test_pairwise_logistic_detector_fits_and_returns_uncertainty_metadata():
    pytest.importorskip("sklearn")
    samples = load_jsonl(ROOT / "data" / "synthetic_v0.jsonl")
    detector = PairwiseLogisticDetector().fit(samples)

    sample = samples[-1]
    old = make_snapshot(
        server_id="ml-test",
        tool=sample.old_tool,
        approval_state="approved",
    )
    new = make_snapshot(server_id="ml-test", tool=sample.new_tool)

    assessment = detector(build_delta(old, new))

    assert assessment.probabilities
    assert assessment.confidence is not None
    assert 0.0 <= assessment.confidence <= 1.0
    assert abs(sum(assessment.probabilities.values()) - 1.0) < 1e-5


def test_high_threshold_forces_abstention():
    pytest.importorskip("sklearn")
    samples = load_jsonl(ROOT / "data" / "synthetic_v0.jsonl")
    detector = PairwiseLogisticDetector(
        confidence_threshold=1.0,
        margin_threshold=1.0,
    ).fit(samples)

    sample = samples[3]
    old = make_snapshot(server_id="ml-test", tool=sample.old_tool, approval_state="approved")
    new = make_snapshot(server_id="ml-test", tool=sample.new_tool)

    assessment = detector(build_delta(old, new))

    assert assessment.abstained is True
    assert assessment.recommended_action == "require_reconsent"
    assert assessment.uncertainty_reason
