from __future__ import annotations

from .models import ChangeClass, RiskAssessment, ToolDelta


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

    if s.required_added:
        score += min(20.0, 8.0 * len(s.required_added))
        reasons.append(f"New required parameters: {', '.join(s.required_added)}")

    if s.imperative_terms_added:
        score += min(25.0, 7.0 * len(s.imperative_terms_added))
        reasons.append(f"New imperative / instruction terms: {', '.join(s.imperative_terms_added)}")

    if s.urls_added:
        score += min(12.0, 5.0 * len(s.urls_added))
        reasons.append(f"New external URLs: {', '.join(s.urls_added)}")

    if s.cross_tool_references_added:
        score += min(15.0, 6.0 * len(s.cross_tool_references_added))
        reasons.append(
            "New cross-tool references: " + ", ".join(s.cross_tool_references_added)
        )

    score += min(15.0, 25.0 * delta.lexical_change_ratio)
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
    )
