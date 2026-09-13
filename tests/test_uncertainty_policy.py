from driftguard.models import ChangeClass, RiskAssessment
from driftguard.runtime import DefaultPolicy, EnforcementAction


def test_policy_requires_reconsent_when_detector_abstains():
    assessment = RiskAssessment(
        change_class=ChangeClass.BENIGN_MAINTENANCE,
        risk_score=20.0,
        recommended_action="require_reconsent",
        abstained=True,
        confidence=0.41,
        uncertainty_reason="Low-confidence prediction.",
    )

    decision = DefaultPolicy().decide(assessment)

    assert decision.action == EnforcementAction.REQUIRE_RECONSENT
    assert "Low-confidence" in decision.reason
