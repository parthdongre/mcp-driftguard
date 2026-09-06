from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .canonicalize import make_snapshot
from .consent_policy import (
    ConsentPolicyMetrics,
    PolicySelection,
    SequenceRiskTrace,
    evaluate_consent_policy,
    select_consent_policy,
)
from .dataset import TrajectoryDatasetRecord, TrajectoryStep
from .diff import build_delta
from .features import extract_pair_features
from .models import ChangeClass
from .mutations import (
    add_mutating_behavior,
    add_optional_format_parameter,
    benign_clarification,
    broaden_scope,
    build_low_and_slow_trajectory,
)
from .temporal import TemporalConfig, research_risk_signal


class TemporalStrategy(StrEnum):
    """Model-independent comparison strategies for the temporal research question."""

    ADJACENT_ONLY = "adjacent_only"
    APPROVED_BASELINE = "approved_baseline"
    SEQUENTIAL = "sequential"


@dataclass(frozen=True)
class StrategyEvaluation:
    strategy: TemporalStrategy
    selection: PolicySelection
    validation_metrics: ConsentPolicyMetrics
    test_metrics: ConsentPolicyMetrics


def _approved_index(trajectory: TrajectoryDatasetRecord) -> int:
    for index, step in enumerate(trajectory.steps):
        if step.version_id == trajectory.approved_version_id:
            return index
    raise ValueError(
        f"Approved version {trajectory.approved_version_id!r} is missing from "
        f"trajectory {trajectory.trajectory_id!r}"
    )


def _attack_onset(trajectory: TrajectoryDatasetRecord, approved_index: int) -> int | None:
    if trajectory.final_label is not ChangeClass.MALICIOUS_DRIFT:
        return None
    for absolute_index, step in enumerate(trajectory.steps[approved_index + 1 :], start=approved_index + 1):
        if step.attack_family:
            return absolute_index - approved_index - 1
    for absolute_index, step in enumerate(trajectory.steps[approved_index + 1 :], start=approved_index + 1):
        if step.transition_label is ChangeClass.MALICIOUS_DRIFT:
            return absolute_index - approved_index - 1
    return None


def trajectory_signal_trace(
    trajectory: TrajectoryDatasetRecord,
    strategy: TemporalStrategy,
    *,
    temporal_config: TemporalConfig | None = None,
) -> SequenceRiskTrace:
    """Convert one tool lineage into risk/capability scores without fitting a model.

    ``adjacent_only`` sees only T[t-1] -> T[t]. ``approved_baseline`` always compares
    T[0] -> T[t]. ``sequential`` combines the approved-baseline signal with a decayed
    CUSUM over locally small transitions. All strategies expose the same cumulative
    capability score to the consent layer so the comparison isolates malicious-drift
    memory rather than intentionally disabling C2 re-consent for one baseline.
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
    malicious_scores: list[float] = []
    capability_scores: list[float] = []

    for step in trajectory.steps[approved_index + 1 :]:
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
        else:  # pragma: no cover - exhaustive guard for future enum members
            raise ValueError(f"Unsupported temporal strategy: {strategy}")

        malicious_scores.append(round(float(malicious), 6))
        capability_scores.append(round(baseline_features.capability_escalation_score, 6))
        previous = current

    if not malicious_scores:
        raise ValueError("Trajectory has no observations after its approved version")

    return SequenceRiskTrace(
        trace_id=trajectory.trajectory_id,
        final_label=trajectory.final_label,
        malicious_scores=tuple(malicious_scores),
        capability_scores=tuple(capability_scores),
        attack_onset=_attack_onset(trajectory, approved_index),
    )


def _threshold_grid(step: float = 0.05) -> tuple[float, ...]:
    if not 0.0 < step <= 1.0:
        raise ValueError("step must be in (0, 1]")
    count = int(round(1.0 / step))
    return tuple(round(index * step, 6) for index in range(1, count + 1))


def compare_temporal_strategies(
    validation: list[TrajectoryDatasetRecord],
    test: list[TrajectoryDatasetRecord],
    *,
    temporal_config: TemporalConfig | None = None,
    threshold_step: float = 0.05,
    min_malicious_detection: float = 0.95,
    max_benign_block_rate: float = 0.03,
    max_benign_reconsent_rate: float = 0.10,
) -> list[StrategyEvaluation]:
    """Tune each strategy on validation lineages and evaluate once on held-out lineages."""

    if not validation or not test:
        raise ValueError("Both validation and test trajectory sets are required")
    grid = _threshold_grid(threshold_step)
    results: list[StrategyEvaluation] = []
    for strategy in TemporalStrategy:
        validation_traces = [
            trajectory_signal_trace(item, strategy, temporal_config=temporal_config)
            for item in validation
        ]
        test_traces = [
            trajectory_signal_trace(item, strategy, temporal_config=temporal_config)
            for item in test
        ]
        selection = select_consent_policy(
            validation_traces,
            reconsent_grid=grid,
            block_grid=grid,
            min_malicious_detection=min_malicious_detection,
            max_benign_block_rate=max_benign_block_rate,
            max_benign_reconsent_rate=max_benign_reconsent_rate,
        )
        validation_metrics = evaluate_consent_policy(
            validation_traces,
            selection.thresholds,
        )
        test_metrics = evaluate_consent_policy(test_traces, selection.thresholds)
        results.append(
            StrategyEvaluation(
                strategy=strategy,
                selection=selection,
                validation_metrics=validation_metrics,
                test_metrics=test_metrics,
            )
        )
    return results


def _base_tool(name: str, description: str) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Repository search query.",
                }
            },
            "required": ["query"],
        },
        "annotations": {"readOnlyHint": True},
    }


def _trajectory(
    *,
    trajectory_id: str,
    repository_id: str,
    base: dict[str, Any],
    versions: list[tuple[dict[str, Any], ChangeClass, str | None]],
    final_label: ChangeClass,
) -> TrajectoryDatasetRecord:
    steps = [
        TrajectoryStep(
            version_id="v0",
            tool=base,
            transition_label=ChangeClass.NO_MEANINGFUL_CHANGE,
        )
    ]
    for index, (tool, label, attack_family) in enumerate(versions, start=1):
        steps.append(
            TrajectoryStep(
                version_id=f"v{index}",
                tool=tool,
                transition_label=label,
                attack_family=attack_family,
            )
        )
    return TrajectoryDatasetRecord(
        trajectory_id=trajectory_id,
        repository_id=repository_id,
        server_id=f"server:{repository_id}",
        tool_name=str(base["name"]),
        approved_version_id="v0",
        steps=steps,
        final_label=final_label,
        provenance="controlled_temporal_benchmark",
        notes="Controlled development trajectory; not independent publication evidence.",
    )


def _benign_trajectory(
    trajectory_id: str,
    repository_id: str,
    base: dict[str, Any],
) -> TrajectoryDatasetRecord:
    v1 = benign_clarification(base)
    v2 = add_optional_format_parameter(v1)
    return _trajectory(
        trajectory_id=trajectory_id,
        repository_id=repository_id,
        base=base,
        versions=[
            (v1, ChangeClass.BENIGN_MAINTENANCE, None),
            (v2, ChangeClass.BENIGN_MAINTENANCE, None),
        ],
        final_label=ChangeClass.BENIGN_MAINTENANCE,
    )


def _capability_trajectory(
    trajectory_id: str,
    repository_id: str,
    base: dict[str, Any],
    *,
    mutation: str,
) -> TrajectoryDatasetRecord:
    v1 = benign_clarification(base)
    v2 = add_optional_format_parameter(v1)
    if mutation == "scope":
        v3 = broaden_scope(v2)
        family = "legitimate_scope_expansion"
    elif mutation == "write":
        v3 = add_mutating_behavior(v2)
        family = "legitimate_write_expansion"
    else:
        raise ValueError(f"Unknown capability mutation: {mutation}")
    return _trajectory(
        trajectory_id=trajectory_id,
        repository_id=repository_id,
        base=base,
        versions=[
            (v1, ChangeClass.BENIGN_MAINTENANCE, None),
            (v2, ChangeClass.BENIGN_MAINTENANCE, None),
            (v3, ChangeClass.CAPABILITY_EXPANSION, family),
        ],
        final_label=ChangeClass.CAPABILITY_EXPANSION,
    )


def controlled_temporal_split() -> tuple[list[TrajectoryDatasetRecord], list[TrajectoryDatasetRecord]]:
    """Return repository-disjoint validation/test lineages for development experiments.

    This intentionally small deterministic suite exists to test the experimental plumbing
    and expose whether a detector can exploit history. It must not be reported as external
    or real-world benchmark evidence.
    """

    templates = [
        ("alpha", "search_repo", "Search repository files for matching source code."),
        ("beta", "inspect_repo", "Inspect repository files that match a developer query."),
        ("gamma", "find_code", "Find source code and documentation in a repository."),
        ("delta", "lookup_repo", "Look up repository content relevant to a query."),
    ]
    groups: list[list[TrajectoryDatasetRecord]] = []
    for index, (slug, name, description) in enumerate(templates):
        repository_id = f"controlled/{slug}"
        base = _base_tool(name, description)
        groups.append(
            [
                _benign_trajectory(f"{slug}:benign", repository_id, base),
                _capability_trajectory(
                    f"{slug}:c2",
                    repository_id,
                    base,
                    mutation="scope" if index % 2 == 0 else "write",
                ),
                build_low_and_slow_trajectory(
                    repository_id=repository_id,
                    server_id=f"server:{repository_id}",
                    tool=base,
                    trajectory_id=f"{slug}:bounded-c3",
                ),
            ]
        )

    validation = groups[0] + groups[1]
    test = groups[2] + groups[3]
    return validation, test
