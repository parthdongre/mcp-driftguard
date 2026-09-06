from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from .canonicalize import make_snapshot
from .consent_policy import ConsentPolicyThresholds, PolicyAction
from .dataset import TrajectoryDatasetRecord
from .diff import build_delta
from .features import extract_pair_features
from .models import ChangeClass
from .temporal import TemporalConfig, research_risk_signal
from .trajectory_benchmark import TemporalStrategy


@dataclass(frozen=True)
class PolicyActionEvent:
    observation_index: int
    version_id: str
    action: PolicyAction
    malicious_score: float
    capability_score: float


@dataclass(frozen=True)
class StatefulTrajectoryOutcome:
    trace_id: str
    final_label: ChangeClass
    attack_onset: int | None
    events: tuple[PolicyActionEvent, ...]
    observations_seen: int


@dataclass(frozen=True)
class StatefulPolicyMetrics:
    malicious_post_onset_block_rate: float
    malicious_post_onset_intervention_rate: float
    malicious_pre_onset_block_rate: float
    c2_reconsent_rate: float
    c2_block_rate: float
    benign_intervention_rate: float
    mean_post_onset_block_delay: float | None
    reconsents_per_trace: float
    traces: int


@dataclass(frozen=True)
class StatefulPolicySelection:
    thresholds: ConsentPolicyThresholds
    metrics: StatefulPolicyMetrics
    objective: float
    feasible: bool


def _approved_index(trajectory: TrajectoryDatasetRecord) -> int:
    for index, step in enumerate(trajectory.steps):
        if step.version_id == trajectory.approved_version_id:
            return index
    raise ValueError(
        f"Approved version {trajectory.approved_version_id!r} missing from "
        f"trajectory {trajectory.trajectory_id!r}"
    )


def _attack_onset(trajectory: TrajectoryDatasetRecord, approved_index: int) -> int | None:
    if trajectory.final_label is not ChangeClass.MALICIOUS_DRIFT:
        return None
    for absolute_index, step in enumerate(
        trajectory.steps[approved_index + 1 :], start=approved_index + 1
    ):
        if step.attack_family:
            return absolute_index - approved_index - 1
    for absolute_index, step in enumerate(
        trajectory.steps[approved_index + 1 :], start=approved_index + 1
    ):
        if step.transition_label is ChangeClass.MALICIOUS_DRIFT:
            return absolute_index - approved_index - 1
    return None


def simulate_stateful_policy(
    trajectory: TrajectoryDatasetRecord,
    strategy: TemporalStrategy,
    thresholds: ConsentPolicyThresholds,
    *,
    temporal_config: TemporalConfig | None = None,
) -> StatefulTrajectoryOutcome:
    """Apply a consent policy while honoring re-consent as a new trusted baseline.

    Static risk traces are useful diagnostics, but an MCP host that re-consents to a C2
    update should not keep comparing every later version to the obsolete pre-consent
    snapshot. This simulator resets the approved baseline and sequential memory after each
    re-consent, then continues monitoring subsequent updates. A block terminates the trace.
    """

    cfg = temporal_config or TemporalConfig()
    approved_index = _approved_index(trajectory)
    approved_step = trajectory.steps[approved_index]
    approved = make_snapshot(
        server_id=trajectory.server_id,
        tool=approved_step.tool,
        approval_state="approved",
    )
    previous = approved
    cusum = 0.0
    events: list[PolicyActionEvent] = []
    observations_seen = 0

    for observation_index, step in enumerate(trajectory.steps[approved_index + 1 :]):
        current = make_snapshot(server_id=trajectory.server_id, tool=step.tool)
        local_features = extract_pair_features(build_delta(previous, current))
        baseline_features = extract_pair_features(build_delta(approved, current))
        local_risk = research_risk_signal(local_features)
        baseline_risk = research_risk_signal(baseline_features)
        cusum = max(
            0.0,
            cfg.memory_decay * cusum + (local_risk - cfg.reference_drift),
        )

        if strategy is TemporalStrategy.ADJACENT_ONLY:
            malicious = local_risk
        elif strategy is TemporalStrategy.APPROVED_BASELINE:
            malicious = baseline_risk
        elif strategy is TemporalStrategy.SEQUENTIAL:
            malicious = max(baseline_risk, min(1.0, cusum))
        else:  # pragma: no cover
            raise ValueError(f"Unsupported temporal strategy: {strategy}")

        capability = float(baseline_features.capability_escalation_score)
        observations_seen += 1
        if malicious >= thresholds.block_threshold:
            events.append(
                PolicyActionEvent(
                    observation_index=observation_index,
                    version_id=step.version_id,
                    action=PolicyAction.BLOCK,
                    malicious_score=round(float(malicious), 6),
                    capability_score=round(capability, 6),
                )
            )
            break

        if capability >= thresholds.reconsent_threshold:
            events.append(
                PolicyActionEvent(
                    observation_index=observation_index,
                    version_id=step.version_id,
                    action=PolicyAction.RECONSENT,
                    malicious_score=round(float(malicious), 6),
                    capability_score=round(capability, 6),
                )
            )
            approved = make_snapshot(
                server_id=trajectory.server_id,
                tool=step.tool,
                approval_state="approved",
            )
            previous = approved
            cusum = 0.0
            continue

        previous = current

    return StatefulTrajectoryOutcome(
        trace_id=trajectory.trajectory_id,
        final_label=trajectory.final_label,
        attack_onset=_attack_onset(trajectory, approved_index),
        events=tuple(events),
        observations_seen=observations_seen,
    )


def evaluate_stateful_policy(
    trajectories: list[TrajectoryDatasetRecord],
    strategy: TemporalStrategy,
    thresholds: ConsentPolicyThresholds,
    *,
    temporal_config: TemporalConfig | None = None,
) -> StatefulPolicyMetrics:
    if not trajectories:
        raise ValueError("At least one trajectory is required")

    outcomes = [
        simulate_stateful_policy(
            item,
            strategy,
            thresholds,
            temporal_config=temporal_config,
        )
        for item in trajectories
    ]
    malicious = [item for item in outcomes if item.final_label is ChangeClass.MALICIOUS_DRIFT]
    c2 = [item for item in outcomes if item.final_label is ChangeClass.CAPABILITY_EXPANSION]
    benign = [
        item
        for item in outcomes
        if item.final_label in {ChangeClass.NO_MEANINGFUL_CHANGE, ChangeClass.BENIGN_MAINTENANCE}
    ]

    post_block = 0
    post_intervention = 0
    pre_block = 0
    delays: list[float] = []
    for outcome in malicious:
        if outcome.attack_onset is None:
            continue
        onset = outcome.attack_onset
        pre_blocks = [
            event
            for event in outcome.events
            if event.action is PolicyAction.BLOCK and event.observation_index < onset
        ]
        if pre_blocks:
            pre_block += 1

        post_events = [
            event for event in outcome.events if event.observation_index >= onset
        ]
        if post_events:
            post_intervention += 1
        post_blocks = [event for event in post_events if event.action is PolicyAction.BLOCK]
        if post_blocks:
            post_block += 1
            delays.append(float(post_blocks[0].observation_index - onset))

    def has_action(outcome: StatefulTrajectoryOutcome, action: PolicyAction) -> bool:
        return any(event.action is action for event in outcome.events)

    c2_reconsent = sum(has_action(item, PolicyAction.RECONSENT) for item in c2)
    c2_block = sum(has_action(item, PolicyAction.BLOCK) for item in c2)
    benign_intervention = sum(bool(item.events) for item in benign)
    reconsents = sum(
        event.action is PolicyAction.RECONSENT
        for item in outcomes
        for event in item.events
    )

    return StatefulPolicyMetrics(
        malicious_post_onset_block_rate=(post_block / len(malicious) if malicious else 0.0),
        malicious_post_onset_intervention_rate=(
            post_intervention / len(malicious) if malicious else 0.0
        ),
        malicious_pre_onset_block_rate=(pre_block / len(malicious) if malicious else 0.0),
        c2_reconsent_rate=(c2_reconsent / len(c2) if c2 else 0.0),
        c2_block_rate=(c2_block / len(c2) if c2 else 0.0),
        benign_intervention_rate=(
            benign_intervention / len(benign) if benign else 0.0
        ),
        mean_post_onset_block_delay=(mean(delays) if delays else None),
        reconsents_per_trace=reconsents / len(outcomes),
        traces=len(outcomes),
    )


def _objective(metrics: StatefulPolicyMetrics, *, delay_weight: float) -> float:
    delay = metrics.mean_post_onset_block_delay or 0.0
    return (
        5.0 * (1.0 - metrics.malicious_post_onset_block_rate)
        + 2.0 * metrics.malicious_pre_onset_block_rate
        + metrics.benign_intervention_rate
        + 0.50 * metrics.c2_block_rate
        + 0.10 * (1.0 - metrics.c2_reconsent_rate)
        + delay_weight * delay
    )


def select_stateful_policy(
    validation: list[TrajectoryDatasetRecord],
    strategy: TemporalStrategy,
    *,
    temporal_config: TemporalConfig | None = None,
    threshold_step: float = 0.05,
    min_post_onset_block_rate: float = 0.95,
    min_c2_reconsent_rate: float = 0.90,
    max_pre_onset_block_rate: float = 0.03,
    max_c2_block_rate: float = 0.05,
    max_benign_intervention_rate: float = 0.10,
    delay_weight: float = 0.02,
) -> StatefulPolicySelection:
    """Tune thresholds only on validation trajectories under operational constraints."""

    if not validation:
        raise ValueError("At least one validation trajectory is required")
    if not 0.0 < threshold_step <= 1.0:
        raise ValueError("threshold_step must be in (0, 1]")

    count = round(1.0 / threshold_step)
    grid = tuple(round(index * threshold_step, 6) for index in range(1, count + 1))
    candidates: list[StatefulPolicySelection] = []
    for reconsent in grid:
        for block in grid:
            thresholds = ConsentPolicyThresholds(reconsent, block)
            metrics = evaluate_stateful_policy(
                validation,
                strategy,
                thresholds,
                temporal_config=temporal_config,
            )
            feasible = (
                metrics.malicious_post_onset_block_rate >= min_post_onset_block_rate
                and metrics.c2_reconsent_rate >= min_c2_reconsent_rate
                and metrics.malicious_pre_onset_block_rate <= max_pre_onset_block_rate
                and metrics.c2_block_rate <= max_c2_block_rate
                and metrics.benign_intervention_rate <= max_benign_intervention_rate
            )
            candidates.append(
                StatefulPolicySelection(
                    thresholds=thresholds,
                    metrics=metrics,
                    objective=round(_objective(metrics, delay_weight=delay_weight), 8),
                    feasible=feasible,
                )
            )

    feasible = [item for item in candidates if item.feasible]
    pool = feasible or candidates
    return min(
        pool,
        key=lambda item: (
            item.objective,
            item.thresholds.block_threshold,
            item.thresholds.reconsent_threshold,
        ),
    )
