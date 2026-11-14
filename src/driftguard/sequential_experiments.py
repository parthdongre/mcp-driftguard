"""Isolated experimental sequential detectors; never an authorization authority.

These transparent charts measure evidence in a numeric feature stream. They do not
inherit distribution-free false-alarm guarantees from unrelated conformal methods.
Reference moments and thresholds must be selected before observing final test data.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite


def _finite(value: float, name: str) -> None:
    if not isfinite(value):
        raise ValueError(f"{name} must be finite")


@dataclass(frozen=True)
class SequentialObservation:
    index: int
    score: float
    alerted: bool


class EWMAChart:
    """One-sided EWMA chart: z[t] = alpha*x[t] + (1-alpha)*z[t-1].

    The state begins at a fixed benign reference mean. O(1) work and storage per
    observation. Thresholds are empirical, not an asserted analytic ARL bound.
    """

    def __init__(
        self, *, alpha: float = 0.25, reference_mean: float = 0.0,
        threshold: float = 0.35,
    ) -> None:
        for name, value in (
            ("alpha", alpha), ("reference_mean", reference_mean), ("threshold", threshold),
        ):
            _finite(value, name)
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha must be in (0, 1]")
        if threshold < 0:
            raise ValueError("threshold must be non-negative")
        self.alpha = alpha
        self.reference_mean = reference_mean
        self.threshold = threshold
        self.reset()

    def reset(self) -> None:
        self.value = self.reference_mean
        self.observations = 0

    def observe(self, value: float) -> SequentialObservation:
        _finite(value, "observation")
        self.value = self.alpha * value + (1.0 - self.alpha) * self.value
        self.observations += 1
        score = max(0.0, self.value - self.reference_mean)
        return SequentialObservation(self.observations, score, score >= self.threshold)


class MultivariateCUSUM:
    """Maximum of standardized, one-sided coordinate CUSUM charts.

    s[j,t] = max(0, decay*s[j,t-1] + (x[j,t]-mu[j])/scale[j] - allowance).
    The score is max_j s[j,t]. This diagonal method deliberately does not estimate
    cross-feature covariance. O(d) update work and storage. Empirical family-wide
    false alarms must be measured because checking multiple coordinates increases
    opportunities to alert. This is not kernel CUSUM or a conformal e-process.
    """

    def __init__(
        self, reference_mean: Sequence[float], reference_scale: Sequence[float], *,
        allowance: float = 0.5, threshold: float = 5.0, decay: float = 1.0,
    ) -> None:
        self.reference_mean = tuple(float(value) for value in reference_mean)
        self.reference_scale = tuple(float(value) for value in reference_scale)
        if not self.reference_mean or len(self.reference_mean) != len(self.reference_scale):
            raise ValueError("Reference mean and scale must have equal nonzero dimensions")
        for value in (*self.reference_mean, *self.reference_scale, allowance, threshold, decay):
            _finite(value, "Configuration value")
        if any(value <= 0 for value in self.reference_scale):
            raise ValueError("Reference scales must be strictly positive")
        if allowance < 0 or threshold < 0 or not 0.0 < decay <= 1.0:
            raise ValueError("allowance/threshold must be non-negative and decay in (0, 1]")
        self.allowance = allowance
        self.threshold = threshold
        self.decay = decay
        self.reset()

    def reset(self) -> None:
        self.components = [0.0] * len(self.reference_mean)
        self.observations = 0

    def observe(self, values: Sequence[float]) -> SequentialObservation:
        if len(values) != len(self.reference_mean):
            raise ValueError("Observation dimension differs from reference")
        for value in values:
            _finite(value, "Observation")
        self.components = [
            max(0.0, self.decay * accumulated + (value - center) / scale - self.allowance)
            for accumulated, value, center, scale in zip(
                self.components, values, self.reference_mean, self.reference_scale, strict=True
            )
        ]
        self.observations += 1
        score = max(self.components)
        return SequentialObservation(self.observations, score, score >= self.threshold)
