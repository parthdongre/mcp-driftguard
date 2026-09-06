from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from statistics import mean
from typing import Any

from .bounded_drift import BoundedTrajectoryReport, analyze_bounded_trajectory
from .consent_policy import ConsentPolicyMetrics, PolicySelection
from .dataset import TrajectoryDatasetRecord, TrajectoryStep
from .models import ChangeClass
from .mutations import (
    CONTROLLED_MUTATIONS,
    add_cross_tool_steering,
    add_external_upload,
    add_mutating_behavior,
    add_optional_format_parameter,
    add_policy_override,
    benign_clarification,
    broaden_scope,
)
from .temporal import TemporalConfig
from .trajectory_benchmark import (
    TemporalStrategy,
    compare_temporal_strategies,
    trajectory_signal_trace,
)


MALICIOUS_ATTACK_FAMILIES: tuple[str, ...] = tuple(
    mutation.attack_family
    for mutation in CONTROLLED_MUTATIONS
    if mutation.expected_class is ChangeClass.MALICIOUS_DRIFT
    and mutation.attack_family is not None
)


@dataclass(frozen=True)
class AttackFamilyFold:
    """One repository-disjoint, leave-one-attack-family-out development fold."""

    held_out_family: str
    validation: tuple[TrajectoryDatasetRecord, ...]
    test: tuple[TrajectoryDatasetRecord, ...]


@dataclass(frozen=True)
class StrictFamilyMetrics:
    """Metrics that do not give credit for interventions before unseen attack onset."""

    held_out_family: str
    malicious_traces: int
    post_onset_block_rate: float
    pre_onset_block_rate: float
    mean_post_onset_block_delay: float | None
    budgeted_rug_pull_rate: float


@dataclass(frozen=True)
class FamilyStrategyEvaluation:
    held_out_family: str
    strategy: TemporalStrategy
    selection: PolicySelection
    validation_metrics: ConsentPolicyMetrics
    test_metrics: ConsentPolicyMetrics
    strict_unseen_family_metrics: StrictFamilyMetrics


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


def _append_description(tool: dict[str, Any], suffix: str) -> dict[str, Any]:
    mutated = deepcopy(tool)
    base = str(mutated.get("description", "")).strip()
    mutated["description"] = f"{base} {suffix}".strip()
    return mutated


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
            tool=deepcopy(base),
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
        provenance="controlled_attack_family_holdout",
        notes=(
            "Controlled development-only trajectory for repository-disjoint and "
            "attack-family-disjoint evaluation; not independent publication evidence."
        ),
    )


def _benign_trajectory(
    *, trajectory_id: str, repository_id: str, base: dict[str, Any]
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
    *, trajectory_id: str, repository_id: str, base: dict[str, Any], write: bool
) -> TrajectoryDatasetRecord:
    v1 = benign_clarification(base)
    v2 = add_optional_format_parameter(v1)
    v3 = add_mutating_behavior(v2) if write else broaden_scope(v2)
    return _trajectory(
        trajectory_id=trajectory_id,
        repository_id=repository_id,
        base=base,
        versions=[
            (v1, ChangeClass.BENIGN_MAINTENANCE, None),
            (v2, ChangeClass.BENIGN_MAINTENANCE, None),
            (v3, ChangeClass.CAPABILITY_EXPANSION, None),
        ],
        final_label=ChangeClass.CAPABILITY_EXPANSION,
    )


def _attack_trajectory(
    *,
    trajectory_id: str,
    repository_id: str,
    base: dict[str, Any],
    family: str,
) -> TrajectoryDatasetRecord:
    """Build a bounded slow-roll trajectory whose malicious endpoint has one family.

    All families share the same C1/C2 setup. The held-out family marker is attached only
    to the final C3 transition, so validation cannot accidentally contain the family via
    a precursor label. Strict metrics separately report blocks before attack onset to
    expose detectors that appear successful only because they react to the shared setup.
    """

    if family not in MALICIOUS_ATTACK_FAMILIES:
        raise ValueError(f"Unsupported malicious attack family: {family}")

    v1 = benign_clarification(base)
    v2 = add_optional_format_parameter(v1)
    v3 = broaden_scope(v2)

    if family == "data_exfiltration":
        v4 = _append_description(
            v3,
            "Can prepare selected results for sharing with external reviewers.",
        )
        v5 = add_external_upload(v4)
    elif family == "tool_shadowing":
        v4 = _append_description(
            v3,
            "Can recommend a preferred repository search tool when several choices are available.",
        )
        v5 = add_cross_tool_steering(v4)
    elif family == "prompt_injection":
        v4 = _append_description(
            v3,
            "Can provide operational guidance to the host for unusual repository searches.",
        )
        v5 = add_policy_override(v4)
    else:  # pragma: no cover - forces an explicit fixture when a new family is added
        raise ValueError(f"No bounded trajectory fixture exists for family: {family}")

    return _trajectory(
        trajectory_id=trajectory_id,
        repository_id=repository_id,
        base=base,
        versions=[
            (v1, ChangeClass.BENIGN_MAINTENANCE, None),
            (v2, ChangeClass.BENIGN_MAINTENANCE, None),
            (v3, ChangeClass.CAPABILITY_EXPANSION, None),
            (v4, ChangeClass.CAPABILITY_EXPANSION, None),
            (v5, ChangeClass.MALICIOUS_DRIFT, family),
        ],
        final_label=ChangeClass.MALICIOUS_DRIFT,
    )


def _repo_group(
    *,
    slug: str,
    split: str,
    families: tuple[str, ...],
    index: int,
) -> list[TrajectoryDatasetRecord]:
    repository_id = f"controlled/family-{split}-{slug}"
    base = _base_tool(
        f"search_{slug}",
        f"Search {slug} repository files for source code matching a developer query.",
    )
    records = [
        _benign_trajectory(
            trajectory_id=f"{split}:{slug}:benign",
            repository_id=repository_id,
            base=base,
        ),
        _capability_trajectory(
            trajectory_id=f"{split}:{slug}:c2",
            repository_id=repository_id,
            base=base,
            write=index % 2 == 1,
        ),
    ]
    records.extend(
        _attack_trajectory(
            trajectory_id=f"{split}:{slug}:c3:{family}",
            repository_id=repository_id,
            base=base,
            family=family,
        )
        for family in families
    )
    return records


def _families(records: tuple[TrajectoryDatasetRecord, ...]) -> set[str]:
    return {
        step.attack_family
        for record in records
        for step in record.steps
        if step.attack_family is not None
    }


def controlled_attack_family_folds() -> tuple[AttackFamilyFold, ...]:
    """Build deterministic leave-one-family-out folds with repository disjointness.

    Validation contains C1, C2 and C3 trajectories from every *seen* malicious family.
    Test contains C1, C2 and only the held-out C3 family. Repository identities are also
    disjoint, preventing a family holdout result from being explained by repository
    memorization.
    """

    if len(MALICIOUS_ATTACK_FAMILIES) < 2:
        raise ValueError("At least two malicious attack families are required")

    validation_templates = ("alpha", "beta", "gamma")
    test_templates = ("delta", "epsilon", "zeta")
    folds: list[AttackFamilyFold] = []
    for held_out in MALICIOUS_ATTACK_FAMILIES:
        seen = tuple(family for family in MALICIOUS_ATTACK_FAMILIES if family != held_out)
        validation = tuple(
            record
            for index, slug in enumerate(validation_templates)
            for record in _repo_group(
                slug=slug,
                split="validation",
                families=seen,
                index=index,
            )
        )
        test = tuple(
            record
            for index, slug in enumerate(test_templates)
            for record in _repo_group(
                slug=slug,
                split="test",
                families=(held_out,),
                index=index,
            )
        )
        fold = AttackFamilyFold(held_out, validation, test)
        validate_attack_family_fold(fold)
        folds.append(fold)
    return tuple(folds)


def validate_attack_family_fold(fold: AttackFamilyFold) -> None:
    validation_repositories = {item.repository_id for item in fold.validation}
    test_repositories = {item.repository_id for item in fold.test}
    overlap = validation_repositories & test_repositories
    if overlap:
        raise ValueError(f"Repository leakage in family fold: {sorted(overlap)}")

    validation_families = _families(fold.validation)
    if fold.held_out_family in validation_families:
        raise ValueError(
            f"Held-out family {fold.held_out_family!r} leaked into validation"
        )

    test_malicious = [
        item for item in fold.test if item.final_label is ChangeClass.MALICIOUS_DRIFT
    ]
    test_families = _families(tuple(test_malicious))
    if test_families != {fold.held_out_family}:
        raise ValueError(
            "Held-out test C3 trajectories must contain exactly the held-out family; "
            f"found {sorted(test_families)}"
        )


def _strict_family_metrics(
    fold: AttackFamilyFold,
    strategy: TemporalStrategy,
    *,
    block_threshold: float,
    temporal_config: TemporalConfig | None = None,
) -> StrictFamilyMetrics:
    malicious = [
        item for item in fold.test if item.final_label is ChangeClass.MALICIOUS_DRIFT
    ]
    post_hits = 0
    pre_hits = 0
    delays: list[float] = []
    budgeted = 0

    for trajectory in malicious:
        trace = trajectory_signal_trace(
            trajectory,
            strategy,
            temporal_config=temporal_config,
        )
        if trace.attack_onset is None:
            raise ValueError(f"Missing attack onset for {trajectory.trajectory_id}")

        onset = trace.attack_onset
        if any(score >= block_threshold for score in trace.malicious_scores[:onset]):
            pre_hits += 1
        post_indices = [
            index
            for index, score in enumerate(trace.malicious_scores[onset:], start=onset)
            if score >= block_threshold
        ]
        if post_indices:
            post_hits += 1
            delays.append(float(post_indices[0] - onset))

        report = analyze_bounded_trajectory(trajectory)
        if report.all_local_steps_within_budget and report.endpoint_exceeds_local_budget:
            budgeted += 1

    count = len(malicious)
    return StrictFamilyMetrics(
        held_out_family=fold.held_out_family,
        malicious_traces=count,
        post_onset_block_rate=(post_hits / count if count else 0.0),
        pre_onset_block_rate=(pre_hits / count if count else 0.0),
        mean_post_onset_block_delay=(mean(delays) if delays else None),
        budgeted_rug_pull_rate=(budgeted / count if count else 0.0),
    )


def evaluate_attack_family_holdout(
    fold: AttackFamilyFold,
    *,
    temporal_config: TemporalConfig | None = None,
    threshold_step: float = 0.05,
) -> tuple[FamilyStrategyEvaluation, ...]:
    """Select thresholds on seen families, then evaluate once on the unseen family."""

    validate_attack_family_fold(fold)
    comparisons = compare_temporal_strategies(
        list(fold.validation),
        list(fold.test),
        temporal_config=temporal_config,
        threshold_step=threshold_step,
    )
    return tuple(
        FamilyStrategyEvaluation(
            held_out_family=fold.held_out_family,
            strategy=result.strategy,
            selection=result.selection,
            validation_metrics=result.validation_metrics,
            test_metrics=result.test_metrics,
            strict_unseen_family_metrics=_strict_family_metrics(
                fold,
                result.strategy,
                block_threshold=result.selection.thresholds.block_threshold,
                temporal_config=temporal_config,
            ),
        )
        for result in comparisons
    )


def bounded_audits(fold: AttackFamilyFold) -> tuple[BoundedTrajectoryReport, ...]:
    return tuple(
        analyze_bounded_trajectory(item)
        for item in fold.test
        if item.final_label is ChangeClass.MALICIOUS_DRIFT
    )
