from __future__ import annotations

from .models import ChangeClass, RiskAssessment, RiskContribution, ToolDelta


def hash_only_changed(delta: ToolDelta) -> bool:
    """Integrity baseline: any canonical hash change is an alert."""

    return delta.old.sha256 != delta.new.sha256


def rule_baseline(delta: ToolDelta) -> RiskAssessment:
    """Transparent pre-ML baseline used for demos and later model comparison.

    This intentionally remains simple. It is not the final detector; it gives the
    project a reproducible baseline against which the learned pair classifier can
    be evaluated.
    """

    s = delta.structural
    score = 0.0
    reasons: list[str] = []
    contributions: list[RiskContribution] = []

    if delta.old.sha256 == delta.new.sha256:
        return RiskAssessment(
            change_class=ChangeClass.NO_MEANINGFUL_CHANGE,
            risk_score=0.0,
            reasons=["Canonical tool definition is unchanged."],
            recommended_action="allow",
            probabilities={ChangeClass.NO_MEANINGFUL_CHANGE.value: 1.0},
        )

    if s.sensitive_terms_added:
        contribution = min(35.0, 12.0 + 5.0 * len(s.sensitive_terms_added))
        score += contribution
        reasons.append(f"New sensitive capability terms: {', '.join(s.sensitive_terms_added)}")
        contributions.append(
            RiskContribution(
                signal="sensitive_terms_added",
                points=contribution,
                evidence=s.sensitive_terms_added,
            )
        )

    if s.required_added:
        contribution = min(20.0, 8.0 * len(s.required_added))
        score += contribution
        reasons.append(f"New required parameters: {', '.join(s.required_added)}")
        contributions.append(
            RiskContribution(
                signal="required_parameters_added",
                points=contribution,
                evidence=s.required_added,
            )
        )

    if s.imperative_terms_added:
        contribution = min(25.0, 7.0 * len(s.imperative_terms_added))
        score += contribution
        reasons.append(f"New imperative / instruction terms: {', '.join(s.imperative_terms_added)}")
        contributions.append(
            RiskContribution(
                signal="imperative_terms_added",
                points=contribution,
                evidence=s.imperative_terms_added,
            )
        )

    if s.urls_added:
        contribution = min(12.0, 5.0 * len(s.urls_added))
        score += contribution
        reasons.append(f"New external URLs: {', '.join(s.urls_added)}")
        contributions.append(
            RiskContribution(
                signal="external_urls_added",
                points=contribution,
                evidence=s.urls_added,
            )
        )

    if s.cross_tool_references_added:
        contribution = min(15.0, 6.0 * len(s.cross_tool_references_added))
        score += contribution
        reasons.append(
            "New cross-tool references: " + ", ".join(s.cross_tool_references_added)
        )
        contributions.append(
            RiskContribution(
                signal="cross_tool_references_added",
                points=contribution,
                evidence=s.cross_tool_references_added,
            )
        )

    lexical_contribution = min(15.0, 25.0 * delta.lexical_change_ratio)
    if lexical_contribution:
        score += lexical_contribution
        contributions.append(
            RiskContribution(
                signal="lexical_change",
                points=round(lexical_contribution, 2),
                evidence=[f"change_ratio={delta.lexical_change_ratio:.4f}"],
            )
        )

    score = min(100.0, round(score, 2))

    if score >= 80:
        change_class = ChangeClass.MALICIOUS_DRIFT
        action = "quarantine"
    elif score >= 45:
        change_class = ChangeClass.CAPABILITY_EXPANSION
        action = "require_reconsent"
    else:
        change_class = ChangeClass.BENIGN_MAINTENANCE
        action = "allow_and_log"

    if not reasons:
        reasons.append("Definition changed without a high-risk structural signal in the rule baseline.")

    return RiskAssessment(
        change_class=change_class,
        risk_score=score,
        reasons=reasons,
        recommended_action=action,
        contributions=contributions,
    )
