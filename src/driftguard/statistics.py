from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import isfinite
from random import Random
from statistics import mean
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class ConfidenceInterval:
    estimate: float
    lower: float
    upper: float
    confidence: float
    bootstrap_samples: int


@dataclass(frozen=True)
class ClusterConfidenceInterval(ConfidenceInterval):
    clusters: int
    observations: int


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
    if any(not isfinite(value) for value in sample):
        raise ValueError("Bootstrap observations must be finite")
    rng = Random(seed)
    boot: list[float] = []
    for _ in range(bootstrap_samples):
        resampled = [sample[rng.randrange(len(sample))] for _ in range(len(sample))]
        boot.append(float(statistic(resampled)))
    if any(not isfinite(value) for value in boot):
        raise ValueError("Bootstrap statistic must return finite values")

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


def _cluster_indices(cluster_ids: Sequence[str], observations: int) -> list[list[int]]:
    if len(cluster_ids) != observations:
        raise ValueError("cluster_ids must have one entry per observation")
    groups: dict[str, list[int]] = {}
    for index, cluster_id in enumerate(cluster_ids):
        if not isinstance(cluster_id, str) or not cluster_id.strip():
            raise ValueError("Cluster identifiers must be non-blank strings")
        groups.setdefault(cluster_id, []).append(index)
    if len(groups) < 2:
        raise ValueError("Cluster bootstrap requires at least two independent clusters")
    return [groups[key] for key in sorted(groups)]


def cluster_bootstrap_confidence_interval(
    values: Sequence[T],
    cluster_ids: Sequence[str],
    *,
    statistic: Callable[[Sequence[T]], float] = mean,
    confidence: float = 0.95,
    bootstrap_samples: int = 5000,
    seed: int = 20260906,
) -> ClusterConfidenceInterval:
    """Resample whole repositories/servers and recompute a pooled-record statistic.

    Every replicate draws the original number of clusters with replacement, preserving
    all records and their multiplicity within each selected cluster. This estimates a
    record-weighted statistic; for an equal-repository estimand, bootstrap repository
    metric values with ``bootstrap_confidence_interval`` instead. Clusters must be
    defensibly independent. Percentile intervals can degenerate on constant outcomes.
    """

    return _cluster_interval(
        values,
        values,
        cluster_ids,
        statistic=statistic,
        confidence=confidence,
        bootstrap_samples=bootstrap_samples,
        seed=seed,
        single_sample=True,
    )


def paired_cluster_bootstrap_difference(
    baseline: Sequence[T],
    proposed: Sequence[T],
    cluster_ids: Sequence[str],
    *,
    statistic: Callable[[Sequence[T]], float] = mean,
    confidence: float = 0.95,
    bootstrap_samples: int = 5000,
    seed: int = 20260906,
) -> ClusterConfidenceInterval:
    """Paired proposed-minus-baseline interval using identical sampled clusters.

    Inputs must be aligned observations from the same frozen test records. The metric
    is recomputed separately on both resampled record sets, supporting nonlinear
    statistics such as F1 rather than incorrectly averaging record-level differences.
    """

    return _cluster_interval(
        baseline, proposed, cluster_ids, statistic=statistic,
        confidence=confidence, bootstrap_samples=bootstrap_samples, seed=seed,
        single_sample=False,
    )


def _cluster_interval(
    baseline: Sequence[T],
    proposed: Sequence[T],
    cluster_ids: Sequence[str],
    *,
    statistic: Callable[[Sequence[T]], float],
    confidence: float,
    bootstrap_samples: int,
    seed: int,
    single_sample: bool,
) -> ClusterConfidenceInterval:
    if len(baseline) != len(proposed):
        raise ValueError("Paired samples must have equal length and ordering")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be between 0 and 1")
    if bootstrap_samples < 100:
        raise ValueError("bootstrap_samples must be at least 100")
    groups = _cluster_indices(cluster_ids, len(baseline))
    rng = Random(seed)

    def estimate(indices: Sequence[int]) -> float:
        new = float(statistic([proposed[index] for index in indices]))
        old = 0.0 if single_sample else float(
            statistic([baseline[index] for index in indices])
        )
        value = new - old
        if not isfinite(value):
            raise ValueError("Bootstrap statistic must return finite values")
        return value

    point = estimate(range(len(baseline)))
    boot = [
        estimate([
            index
            for _ in groups
            for index in groups[rng.randrange(len(groups))]
        ])
        for _ in range(bootstrap_samples)
    ]
    alpha = 1.0 - confidence
    return ClusterConfidenceInterval(
        estimate=point,
        lower=_percentile(boot, alpha / 2.0),
        upper=_percentile(boot, 1.0 - alpha / 2.0),
        confidence=confidence,
        bootstrap_samples=bootstrap_samples,
        clusters=len(groups),
        observations=len(baseline),
    )
