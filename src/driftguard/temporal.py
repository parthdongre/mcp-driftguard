from __future__ import annotations

from dataclasses import dataclass

from .diff import build_delta
from .features import extract_pair_features
from .models import PairFeatures, TemporalAssessment, ToolSnapshot


@dataclass(frozen=True)
class TemporalConfig:
    """Configuration for the first low-and-slow research baseline."""

    reference_drift: float = 0.08
    cusum_threshold: float = 0.55
    baseline_threshold: float = 0.72
    memory_decay: float = 0.98


def _bounded_structural_risk(features: PairFeatures) -> float:
    s = features.structural_counts
    value = (
        0.05 * s.get("parameters_added", 0.0)
        + 0.09 * s.get("required_added", 0.0)
        + 0.09 * s.get("type_changes", 0.0)
        + 0.08 * s.get("default_changes", 0.0)
        + 0.10 * s.get("sensitive_terms_added", 0.0)
        + 0.08 * s.get("urls_added", 0.0)
        + 0.08 * s.get("cross_tool_references_added", 0.0)
        + 0.08 * s.get("imperative_terms_added", 0.0)
    )
    return min(1.0, value)


def research_risk_signal(features: PairFeatures) -> float:
    """Transparent scalar used only by the sequential baseline.

    The final paper model will learn this relationship. Keeping the first temporal
    detector deterministic lets us test whether temporal accumulation itself adds
    value before introducing a trained classifier.
    """

    max_view_drift = max(features.view_lexical_drift.values(), default=0.0)
    structural = _bounded_structural_risk(features)
    score = (
        0.45 * features.capability_escalation_score
        + 0.30 * max_view_drift
        + 0.20 * structural
        + 0.05 * features.lexical_change_ratio
    )
    return round(min(1.0, max(0.0, score)), 6)


class SequentialDriftMonitor:
    """Track one approved tool lineage and detect gradual post-approval drift.

    Two signals are maintained:
    1. local CUSUM over consecutive updates, for repeated small suspicious steps;
    2. direct approved-baseline risk, for cumulative movement that becomes dangerous.
    """

    def __init__(self, approved: ToolSnapshot, config: TemporalConfig | None = None) -> None:
        self.config = config or TemporalConfig()
        self.approved = approved
        self.previous = approved
        self.cusum_score = 0.0
        self.versions_seen = 1

    def observe(self, current: ToolSnapshot) -> TemporalAssessment:
        if current.server_id != self.approved.server_id or current.tool_name != self.approved.tool_name:
            raise ValueError("SequentialDriftMonitor can only track one server/tool lineage")

        step_features = extract_pair_features(build_delta(self.previous, current))
        baseline_features = extract_pair_features(build_delta(self.approved, current))
        step_risk = research_risk_signal(step_features)
        baseline_risk = research_risk_signal(baseline_features)

        cfg = self.config
        self.cusum_score = max(
            0.0,
            cfg.memory_decay * self.cusum_score + (step_risk - cfg.reference_drift),
        )
        self.versions_seen += 1
        self.previous = current

        reasons: list[str] = []
        if self.cusum_score >= cfg.cusum_threshold:
            reasons.append("Sequential drift budget exceeded across consecutive updates.")
        if baseline_risk >= cfg.baseline_threshold:
            reasons.append("Current schema is high-risk relative to the last approved baseline.")
        if baseline_features.capability_escalation_score > 0:
            reasons.append(
                "Approved-to-current lineage adds effective capability signals "
                f"(score={baseline_features.capability_escalation_score:.3f})."
            )

        alerted = bool(
            reasons
            and (
                self.cusum_score >= cfg.cusum_threshold
                or baseline_risk >= cfg.baseline_threshold
            )
        )
        return TemporalAssessment(
            tool_name=current.tool_name,
            versions_seen=self.versions_seen,
            step_risk=step_risk,
            baseline_risk=baseline_risk,
            cusum_score=round(self.cusum_score, 6),
            alerted=alerted,
            reasons=reasons,
        )

    def approve(self, snapshot: ToolSnapshot) -> None:
        """Establish a new consent baseline and reset accumulated trust debt."""

        if snapshot.server_id != self.approved.server_id or snapshot.tool_name != self.approved.tool_name:
            raise ValueError("Cannot approve a snapshot from another server/tool lineage")
        self.approved = snapshot
        self.previous = snapshot
        self.cusum_score = 0.0
        self.versions_seen = 1
