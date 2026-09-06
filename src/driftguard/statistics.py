from __future__ import annotations

from dataclasses import dataclass
from random import Random
from statistics import mean
from typing import Callable, Sequence


@dataclass(frozen=True)
class ConfidenceInterval:
    estimate: float
    lower: float
    upper: float
    confidence: float
    bootstrap_samples: int


def _percentile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("Cannot compute a percentile of an empty sample")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def bootstrap_confidence_interval(
    values: Sequence[float],
    *,
    statistic: Callable[[Sequence[float]], float] = mean,
    confidence: float = 0.95,
    bootstrap_samples: int = 5000,
    seed: int = 20260906,
) -> ConfidenceInterval:
    """Non-parametric percentile bootstrap confidence interval.

    Paper experiments should report uncertainty rather than only point estimates. For
    grouped MCP data, callers should pass repository/server-level metric values whenever
    independence at the record level is not defensible.
    """

    if not values:
        raise ValueError("At least one value is required")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be between 0 and 1")
    if bootstrap_samples < 100:
        raise ValueError("bootstrap_samples must be at least 100")

    sample = [float(value) for value in values]
    rng = Random(seed)
    boot: list[float] = []
    for _ in range(bootstrap_samples):
        resampled = [sample[rng.randrange(len(sample))] for _ in range(len(sample))]
        boot.append(float(statistic(resampled)))

    alpha = 1.0 - confidence
    return ConfidenceInterval(
        estimate=float(statistic(sample)),
        lower=_percentile(boot, alpha / 2.0),
        upper=_percentile(boot, 1.0 - alpha / 2.0),
        confidence=confidence,
        bootstrap_samples=bootstrap_samples,
    )


def paired_bootstrap_difference(
    baseline: Sequence[float],
    proposed: Sequence[float],
    *,
    confidence: float = 0.95,
    bootstrap_samples: int = 5000,
    seed: int = 20260906,
) -> ConfidenceInterval:
    """Bootstrap the paired mean improvement of proposed minus baseline.

    Use this for per-repository or per-trajectory comparisons so the paper can report
    whether DriftGuard improves on a baseline with uncertainty, not only a raw delta.
    """

    if len(baseline) != len(proposed):
        raise ValueError("Paired samples must have equal length")
    if not baseline:
        raise ValueError("At least one paired observation is required")
    differences = [float(new) - float(old) for old, new in zip(baseline, proposed, strict=True)]
    return bootstrap_confidence_interval(
        differences,
        confidence=confidence,
        bootstrap_samples=bootstrap_samples,
        seed=seed,
    )
