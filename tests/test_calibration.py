from __future__ import annotations

from driftguard.calibration import binary_brier_score, binary_calibration_metrics


def test_perfect_probabilities_have_zero_brier() -> None:
    assert binary_brier_score([False, True], [0.0, 1.0]) == 0.0


def test_calibration_metrics_detect_confident_error() -> None:
    metrics = binary_calibration_metrics(
        [False, False, True, True],
        [0.05, 0.10, 0.90, 0.95],
        bins=5,
    )
    assert metrics.brier_score < 0.02
    assert metrics.expected_calibration_error < 0.2
    assert metrics.samples == 4


def test_calibration_rejects_invalid_probability() -> None:
    try:
        binary_calibration_metrics([True], [1.2])
    except ValueError as exc:
        assert "Probabilities" in str(exc)
    else:
        raise AssertionError("Expected invalid probability to be rejected")
