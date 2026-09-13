from __future__ import annotations

from pydantic import BaseModel, Field

from .models import ChangeClass, RiskAssessment, RiskContribution


class CounterfactualExplanation(BaseModel):
    """Greedy rule-baseline explanation for crossing the next safer score boundary."""

    current_class: ChangeClass
    target_class: ChangeClass | None = None
    current_score: float = Field(ge=0.0, le=100.0)
    threshold_to_cross: float | None = Field(default=None, ge=0.0, le=100.0)
    required_score_reduction: float = Field(ge=0.0)
    selected_contributions: list[RiskContribution] = Field(default_factory=list)
    attainable: bool
    explanation: str


_TARGETS: dict[ChangeClass, tuple[ChangeClass, float]] = {
    ChangeClass.MALICIOUS_DRIFT: (ChangeClass.CAPABILITY_EXPANSION, 80.0),
    ChangeClass.CAPABILITY_EXPANSION: (ChangeClass.BENIGN_MAINTENANCE, 45.0),
}


def greedy_counterfactual(assessment: RiskAssessment) -> CounterfactualExplanation:
    """Find a small set of rule signals whose removal crosses the next safer threshold.

    This is an explanation of the transparent rule baseline, not a causal security proof.
    Learned detectors can provide their own explainer behind the same product boundary.
    """

    target = _TARGETS.get(assessment.change_class)
    if target is None:
        return CounterfactualExplanation(
            current_class=assessment.change_class,
            current_score=assessment.risk_score,
            required_score_reduction=0.0,
            attainable=False,
            explanation=(
                "No lower rule-score boundary is defined for this class; "
                "C0 additionally requires canonical equivalence."
            ),
        )

    target_class, threshold = target
    required = max(0.0, assessment.risk_score - threshold + 0.01)
    selected: list[RiskContribution] = []
    removed = 0.0

    for contribution in sorted(
        assessment.contributions,
        key=lambda item: item.points,
        reverse=True,
    ):
        selected.append(contribution)
        removed += contribution.points
        if assessment.risk_score - removed < threshold:
            break

    attainable = assessment.risk_score - removed < threshold
    if attainable:
        signals = ", ".join(item.signal for item in selected)
        explanation = (
            f"Removing or neutralizing approximately {removed:.2f} risk points "
            f"from [{signals}] would move the rule score below {threshold:.2f}, "
            f"the {target_class.value} boundary."
        )
    else:
        explanation = (
            "The recorded score contributions are insufficient to cross the next safer "
            "boundary. This can occur when a capped score hides excess raw contribution."
        )

    return CounterfactualExplanation(
        current_class=assessment.change_class,
        target_class=target_class,
        current_score=assessment.risk_score,
        threshold_to_cross=threshold,
        required_score_reduction=round(required, 2),
        selected_contributions=selected,
        attainable=attainable,
        explanation=explanation,
    )
