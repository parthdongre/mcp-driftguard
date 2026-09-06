from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class CalibrationMetrics:
    brier_score: float
    expected_calibration_error: float
    maximum_calibration_error: float
    bins: int
    samples: int


def _validate_binary_inputs(y_true: list[bool], probabilities: list[float]) -> None:
    if len(y_true) != len(probabilities):
        raise ValueError("truth and probabilities must have equal length")
    if not y_true:
        raise ValueError("At least one probability is required")
    if any(not isfinite(value) or not 0.0 <= value <= 1.0 for value in probabilities):
        raise ValueError("Probabilities must be finite values in [0, 1]")


def binary_brier_score(y_true: list[bool], probabilities: list[float]) -> float:
    _validate_binary_inputs(y_true, probabilities)
    return sum((float(target) - probability) ** 2 for target, probability in zip(y_true, probabilities, strict=True)) / len(y_true)


def binary_calibration_metrics(
    y_true: list[bool],
    probabilities: list[float],
    *,
    bins: int = 10,
) -> CalibrationMetrics:
    """Compute Brier score, ECE, and MCE for a binary security probability.

    Bins are fixed-width in probability space. Empty bins do not contribute. The metric
    is deterministic and dependency-free so every model and baseline can share exactly
    the same calibration implementation.
    """

    _validate_binary_inputs(y_true, probabilities)
    if bins < 2:
        raise ValueError("bins must be at least 2")

    weighted_error = 0.0
    maximum_error = 0.0
    for bin_index in range(bins):
        lower = bin_index / bins
        upper = (bin_index + 1) / bins
        members = [
            index
            for index, probability in enumerate(probabilities)
            if (lower <= probability < upper) or (bin_index == bins - 1 and probability == 1.0)
        ]
        if not members:
            continue
        confidence = sum(probabilities[index] for index in members) / len(members)
        frequency = sum(float(y_true[index]) for index in members) / len(members)
        error = abs(confidence - frequency)
        weighted_error += (len(members) / len(y_true)) * error
        maximum_error = max(maximum_error, error)

    return CalibrationMetrics(
        brier_score=round(binary_brier_score(y_true, probabilities), 8),
        expected_calibration_error=round(weighted_error, 8),
        maximum_calibration_error=round(maximum_error, 8),
        bins=bins,
        samples=len(y_true),
    )
