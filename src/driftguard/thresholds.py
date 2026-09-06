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
    unique = sorted({float(value) for value in values})
    epsilon = max(1e-12, abs(unique[-1]) * 1e-12)
    return [unique[-1] + epsilon, *reversed(unique)]


def _validate_inputs(
    values: Iterable[float],
    labels: Iterable[ChangeClass],
) -> tuple[list[float], list[ChangeClass]]:
    scores = [float(value) for value in values]
    truth_labels = list(labels)
    if len(scores) != len(truth_labels):
        raise ValueError("values and labels must have equal length")
    if not scores:
        raise ValueError("At least one validation example is required")
    return scores, truth_labels


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
    makes the selection deterministic and conservative. For highly separable security
    scores, `tune_margin_threshold` is often preferable because it chooses the middle
    of the validation separation gap instead of hugging the positive class boundary.
    """

    scores, truth_labels = _validate_inputs(values, labels)
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


def tune_margin_threshold(
    values: Iterable[float],
    labels: Iterable[ChangeClass],
    *,
    positive_labels: tuple[ChangeClass, ...] = (ChangeClass.MALICIOUS_DRIFT,),
    fallback_objective: str = "f1",
) -> ThresholdSelection:
    """Choose a validation-only threshold with maximum class-separation margin.

    If validation negatives and positives are perfectly separated, the threshold is the
    midpoint between the largest negative score and the smallest positive score. This
    avoids an unstable threshold sitting directly on the least-confident known attack.
    If the classes overlap, the function falls back to ordinary objective-based tuning.
    """

    scores, truth_labels = _validate_inputs(values, labels)
    positive = set(positive_labels)
    pairs = [(score, label in positive) for score, label in zip(scores, truth_labels, strict=True)]
    positive_scores = [score for score, is_positive in pairs if is_positive]
    negative_scores = [score for score, is_positive in pairs if not is_positive]
    if not positive_scores or not negative_scores:
        return tune_binary_threshold(
            scores,
            truth_labels,
            positive_labels=positive_labels,
            objective=fallback_objective,
        )

    max_negative = max(negative_scores)
    min_positive = min(positive_scores)
    if max_negative >= min_positive:
        return tune_binary_threshold(
            scores,
            truth_labels,
            positive_labels=positive_labels,
            objective=fallback_objective,
        )

    threshold = (max_negative + min_positive) / 2.0
    y_true = [label in positive for label in truth_labels]
    metrics = binary_metrics(y_true, [value >= threshold for value in scores])
    return ThresholdSelection(
        threshold=threshold,
        objective="validation_margin",
        objective_value=min_positive - max_negative,
        metrics=metrics,
        candidates_evaluated=2,
    )
