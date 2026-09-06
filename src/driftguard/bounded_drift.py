from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .canonicalize import make_snapshot
from .dataset import TrajectoryDatasetRecord
from .diff import build_delta
from .features import extract_pair_features
from .temporal import research_risk_signal


@dataclass(frozen=True)
class LocalDriftBudget:
    """Maximum allowed change in one adversarially stealthy version step.

    The budget formalizes a low-and-slow attacker: every local transition must remain
    small enough to look plausibly benign, while the approved-to-current endpoint may
    accumulate a much larger security-relevant change.
    """

    max_risk_signal: float = 0.35
    max_lexical_change_ratio: float = 0.45
    max_capability_escalation: float = 0.35
    max_structural_events: int = 4
    max_sensitive_terms_added: int = 1
    max_urls_added: int = 1


@dataclass(frozen=True)
class DriftStepReport:
    index: int
    risk_signal: float
    lexical_change_ratio: float
    capability_escalation: float
    structural_events: int
    sensitive_terms_added: int
    urls_added: int
    within_budget: bool
    violations: tuple[str, ...]


@dataclass(frozen=True)
class BoundedTrajectoryReport:
    trajectory_id: str
    steps: tuple[DriftStepReport, ...]
    all_local_steps_within_budget: bool
    approved_to_final_risk: float
    approved_to_final_capability_escalation: float
    endpoint_exceeds_local_budget: bool


def _counts(old_tool: dict[str, Any], new_tool: dict[str, Any]):
    old = make_snapshot(server_id="bounded-drift", tool=old_tool, approval_state="approved")
    new = make_snapshot(server_id="bounded-drift", tool=new_tool)
    features = extract_pair_features(build_delta(old, new))
    counts = features.structural_counts
    structural_events = int(
        counts.get("parameters_added", 0)
        + counts.get("parameters_removed", 0)
        + counts.get("required_added", 0)
        + counts.get("required_removed", 0)
        + counts.get("type_changes", 0)
        + counts.get("default_changes", 0)
        + counts.get("enum_changes", 0)
        + counts.get("urls_added", 0)
        + counts.get("cross_tool_references_added", 0)
    )
    return features, structural_events


def analyze_step(
    old_tool: dict[str, Any],
    new_tool: dict[str, Any],
    *,
    index: int,
    budget: LocalDriftBudget | None = None,
) -> DriftStepReport:
    budget = budget or LocalDriftBudget()
    features, structural_events = _counts(old_tool, new_tool)
    counts = features.structural_counts
    risk = research_risk_signal(features)
    lexical = float(features.lexical_change_ratio)
    capability = float(features.capability_escalation_score)
    sensitive = int(counts.get("sensitive_terms_added", 0))
    urls = int(counts.get("urls_added", 0))

    violations: list[str] = []
    if risk > budget.max_risk_signal:
        violations.append("risk_signal")
    if lexical > budget.max_lexical_change_ratio:
        violations.append("lexical_change_ratio")
    if capability > budget.max_capability_escalation:
        violations.append("capability_escalation")
    if structural_events > budget.max_structural_events:
        violations.append("structural_events")
    if sensitive > budget.max_sensitive_terms_added:
        violations.append("sensitive_terms_added")
    if urls > budget.max_urls_added:
        violations.append("urls_added")

    return DriftStepReport(
        index=index,
        risk_signal=risk,
        lexical_change_ratio=round(lexical, 6),
        capability_escalation=round(capability, 6),
        structural_events=structural_events,
        sensitive_terms_added=sensitive,
        urls_added=urls,
        within_budget=not violations,
        violations=tuple(violations),
    )


def analyze_bounded_trajectory(
    trajectory: TrajectoryDatasetRecord,
    *,
    budget: LocalDriftBudget | None = None,
) -> BoundedTrajectoryReport:
    """Measure whether a trajectory is genuinely low-and-slow.

    A useful adversarial sequence should keep every adjacent transition within the local
    stealth budget while producing an approved-to-final endpoint whose risk or capability
    escalation exceeds the same budget. This prevents us from calling a sequence
    low-and-slow when one individual update is already an obvious large jump.
    """

    budget = budget or LocalDriftBudget()
    tools = [step.tool for step in trajectory.steps]
    reports = tuple(
        analyze_step(tools[index - 1], tools[index], index=index, budget=budget)
        for index in range(1, len(tools))
    )

    endpoint_features, _ = _counts(tools[0], tools[-1])
    endpoint_risk = research_risk_signal(endpoint_features)
    endpoint_capability = float(endpoint_features.capability_escalation_score)
    endpoint_exceeds = (
        endpoint_risk > budget.max_risk_signal
        or endpoint_capability > budget.max_capability_escalation
    )
    return BoundedTrajectoryReport(
        trajectory_id=trajectory.trajectory_id,
        steps=reports,
        all_local_steps_within_budget=all(report.within_budget for report in reports),
        approved_to_final_risk=endpoint_risk,
        approved_to_final_capability_escalation=round(endpoint_capability, 6),
        endpoint_exceeds_local_budget=endpoint_exceeds,
    )


def is_budgeted_rug_pull(
    trajectory: TrajectoryDatasetRecord,
    *,
    budget: LocalDriftBudget | None = None,
) -> bool:
    report = analyze_bounded_trajectory(trajectory, budget=budget)
    return report.all_local_steps_within_budget and report.endpoint_exceeds_local_budget
