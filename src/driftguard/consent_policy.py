from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from statistics import mean

from .models import ChangeClass


class PolicyAction(StrEnum):
    ALLOW = "allow"
    RECONSENT = "reconsent"
    BLOCK = "block"


@dataclass(frozen=True)
class SequenceRiskTrace:
    """Model-independent risk trace used for policy selection on validation data."""

    trace_id: str
    final_label: ChangeClass
    malicious_scores: tuple[float, ...]
    capability_scores: tuple[float, ...]
    attack_onset: int | None = None

    def __post_init__(self) -> None:
        if not self.malicious_scores:
            raise ValueError("A sequence trace must contain at least one score")
        if len(self.malicious_scores) != len(self.capability_scores):
            raise ValueError("malicious_scores and capability_scores must have equal length")
        if self.attack_onset is not None and not 0 <= self.attack_onset < len(self.malicious_scores):
            raise ValueError("attack_onset is outside the sequence")


@dataclass(frozen=True)
class ConsentPolicyThresholds:
    reconsent_threshold: float
    block_threshold: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.reconsent_threshold <= 1.0:
            raise ValueError("reconsent_threshold must be in [0, 1]")
        if not 0.0 <= self.block_threshold <= 1.0:
            raise ValueError("block_threshold must be in [0, 1]")


@dataclass(frozen=True)
class ConsentPolicyMetrics:
    malicious_detection_rate: float
    malicious_block_rate: float
    c2_reconsent_rate: float
    benign_reconsent_rate: float
    benign_block_rate: float
    mean_detection_delay: float | None
    interventions_per_trace: float
    traces: int


@dataclass(frozen=True)
class PolicySelection:
    thresholds: ConsentPolicyThresholds
    metrics: ConsentPolicyMetrics
    objective: float
    feasible: bool


def _first_action(
    trace: SequenceRiskTrace, thresholds: ConsentPolicyThresholds
) -> tuple[int, PolicyAction] | None:
    for index, (malicious, capability) in enumerate(
        zip(trace.malicious_scores, trace.capability_scores, strict=True)
    ):
        if malicious >= thresholds.block_threshold:
            return index, PolicyAction.BLOCK
        if capability >= thresholds.reconsent_threshold:
            return index, PolicyAction.RECONSENT
    return None


def evaluate_consent_policy(
    traces: list[SequenceRiskTrace],
    thresholds: ConsentPolicyThresholds,
) -> ConsentPolicyMetrics:
    if not traces:
        raise ValueError("At least one trace is required")

    malicious = [trace for trace in traces if trace.final_label is ChangeClass.MALICIOUS_DRIFT]
    c2 = [trace for trace in traces if trace.final_label is ChangeClass.CAPABILITY_EXPANSION]
    benign = [
        trace
        for trace in traces
        if trace.final_label in {ChangeClass.NO_MEANINGFUL_CHANGE, ChangeClass.BENIGN_MAINTENANCE}
    ]

    outcomes = {trace.trace_id: _first_action(trace, thresholds) for trace in traces}

    malicious_detected = 0
    malicious_blocked = 0
    delays: list[float] = []
    for trace in malicious:
        outcome = outcomes[trace.trace_id]
        if outcome is None:
            continue
        index, action = outcome
        malicious_detected += 1
        if action is PolicyAction.BLOCK:
            malicious_blocked += 1
        if trace.attack_onset is not None:
            delays.append(float(max(0, index - trace.attack_onset)))

    def rate(group: list[SequenceRiskTrace], action: PolicyAction | None = None) -> float:
        if not group:
            return 0.0
        hits = 0
        for trace in group:
            outcome = outcomes[trace.trace_id]
            if outcome is None:
                continue
            if action is None or outcome[1] is action:
                hits += 1
        return hits / len(group)

    interventions = sum(outcome is not None for outcome in outcomes.values())
    return ConsentPolicyMetrics(
        malicious_detection_rate=(malicious_detected / len(malicious) if malicious else 0.0),
        malicious_block_rate=(malicious_blocked / len(malicious) if malicious else 0.0),
        c2_reconsent_rate=rate(c2, PolicyAction.RECONSENT),
        benign_reconsent_rate=rate(benign, PolicyAction.RECONSENT),
        benign_block_rate=rate(benign, PolicyAction.BLOCK),
        mean_detection_delay=(mean(delays) if delays else None),
        interventions_per_trace=interventions / len(traces),
        traces=len(traces),
    )


def _policy_objective(metrics: ConsentPolicyMetrics, *, delay_weight: float) -> float:
    delay = metrics.mean_detection_delay or 0.0
    return (
        metrics.benign_reconsent_rate
        + 2.0 * metrics.benign_block_rate
        + delay_weight * delay
        + 0.10 * (1.0 - metrics.c2_reconsent_rate)
        + 5.0 * (1.0 - metrics.malicious_detection_rate)
    )


def select_consent_policy(
    validation_traces: list[SequenceRiskTrace],
    *,
    reconsent_grid: tuple[float, ...] = (0.25, 0.35, 0.45, 0.55, 0.65),
    block_grid: tuple[float, ...] = (0.45, 0.55, 0.65, 0.75, 0.85),
    min_malicious_detection: float = 0.95,
    max_benign_block_rate: float = 0.03,
    max_benign_reconsent_rate: float = 0.10,
    delay_weight: float = 0.02,
) -> PolicySelection:
    """Choose a consent policy on validation data under explicit security constraints.

    The objective penalizes unnecessary intervention and detection delay. Final test data
    must never be supplied here. This turns threshold selection into the paper's stated
    security/usability optimization rather than tuning solely for raw accuracy.
    """

    if not validation_traces:
        raise ValueError("At least one validation trace is required")

    candidates: list[PolicySelection] = []
    for reconsent in reconsent_grid:
        for block in block_grid:
            thresholds = ConsentPolicyThresholds(reconsent, block)
            metrics = evaluate_consent_policy(validation_traces, thresholds)
            feasible = (
                metrics.malicious_detection_rate >= min_malicious_detection
                and metrics.benign_block_rate <= max_benign_block_rate
                and metrics.benign_reconsent_rate <= max_benign_reconsent_rate
            )
            candidates.append(
                PolicySelection(
                    thresholds=thresholds,
                    metrics=metrics,
                    objective=round(_policy_objective(metrics, delay_weight=delay_weight), 8),
                    feasible=feasible,
                )
            )

    feasible_candidates = [candidate for candidate in candidates if candidate.feasible]
    pool = feasible_candidates or candidates
    return min(pool, key=lambda candidate: (candidate.objective, candidate.thresholds.block_threshold))


def consent_security_pareto_frontier(
    traces: list[SequenceRiskTrace],
    *,
    reconsent_grid: tuple[float, ...] = (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8),
    block_grid: tuple[float, ...] = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9),
) -> list[PolicySelection]:
    """Return non-dominated security/usability policy operating points.

    A point is dominated when another policy has at least as much malicious detection and
    C2 re-consent, no more benign intervention, and no more detection delay, with at least
    one strict improvement. The final paper can plot this frontier against simple policies
    such as reapprove-on-any-change rather than cherry-picking one threshold pair.
    """

    if not traces:
        raise ValueError("At least one trace is required")

    candidates: list[PolicySelection] = []
    for reconsent in reconsent_grid:
        for block in block_grid:
            thresholds = ConsentPolicyThresholds(reconsent, block)
            metrics = evaluate_consent_policy(traces, thresholds)
            candidates.append(
                PolicySelection(
                    thresholds=thresholds,
                    metrics=metrics,
                    objective=round(_policy_objective(metrics, delay_weight=0.02), 8),
                    feasible=True,
                )
            )

    def dominates(left: PolicySelection, right: PolicySelection) -> bool:
        left_delay = left.metrics.mean_detection_delay or 0.0
        right_delay = right.metrics.mean_detection_delay or 0.0
        left_benign = left.metrics.benign_reconsent_rate + left.metrics.benign_block_rate
        right_benign = right.metrics.benign_reconsent_rate + right.metrics.benign_block_rate
        no_worse = (
            left.metrics.malicious_detection_rate >= right.metrics.malicious_detection_rate
            and left.metrics.c2_reconsent_rate >= right.metrics.c2_reconsent_rate
            and left_benign <= right_benign
            and left_delay <= right_delay
        )
        strictly_better = (
            left.metrics.malicious_detection_rate > right.metrics.malicious_detection_rate
            or left.metrics.c2_reconsent_rate > right.metrics.c2_reconsent_rate
            or left_benign < right_benign
            or left_delay < right_delay
        )
        return no_worse and strictly_better

    frontier = [
        candidate
        for candidate in candidates
        if not any(
            dominates(other, candidate)
            for other in candidates
            if other.thresholds != candidate.thresholds
        )
    ]
    return sorted(
        frontier,
        key=lambda item: (
            -item.metrics.malicious_detection_rate,
            item.metrics.benign_reconsent_rate + item.metrics.benign_block_rate,
            item.thresholds.block_threshold,
        ),
    )
