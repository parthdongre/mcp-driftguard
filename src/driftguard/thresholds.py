from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .evaluation import BinaryMetrics, binary_metrics
from .models import ChangeClass


@dataclass(frozen=True)
class ThresholdSelection:
    threshold: float
    objective: str
    objective_value: float
    metrics: BinaryMetrics
    candidates_evaluated: int


def _candidate_thresholds(values: list[float]) -> list[float]:
    if not values:
        return []
    unique = sorted(set(float(value) for value in values))
    epsilon = max(1e-12, abs(unique[-1]) * 1e-12)
    return [unique[-1] + epsilon, *reversed(unique)]


def tune_binary_threshold(
    values: Iterable[float],
    labels: Iterable[ChangeClass],
    *,
    positive_labels: tuple[ChangeClass, ...] = (
        ChangeClass.CAPABILITY_EXPANSION,
        ChangeClass.MALICIOUS_DRIFT,
    ),
    objective: str = "f1",
) -> ThresholdSelection:
    """Choose a scalar alert threshold using validation data only.

    Ties are resolved by lower false-positive rate and then a higher threshold. This
    makes the selection deterministic and slightly conservative when objectives match.
    """

    scores = [float(value) for value in values]
    truth_labels = list(labels)
    if len(scores) != len(truth_labels):
        raise ValueError("values and labels must have equal length")
    if not scores:
        raise ValueError("At least one validation example is required")
    if objective not in {"f1", "accuracy", "recall"}:
        raise ValueError("objective must be one of: f1, accuracy, recall")

    positive = set(positive_labels)
    y_true = [label in positive for label in truth_labels]
    candidates = _candidate_thresholds(scores)
    best: tuple[float, float, float, BinaryMetrics] | None = None

    for threshold in candidates:
        metrics = binary_metrics(y_true, [value >= threshold for value in scores])
        objective_value = float(getattr(metrics, objective))
        ranking = (objective_value, -metrics.false_positive_rate, threshold)
        if best is None or ranking > best[:3]:
            best = (*ranking, metrics)

    assert best is not None
    return ThresholdSelection(
        threshold=best[2],
        objective=objective,
        objective_value=best[0],
        metrics=best[3],
        candidates_evaluated=len(candidates),
    )
