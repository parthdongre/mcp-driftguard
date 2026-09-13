from __future__ import annotations

from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel

from ..models import ChangeClass, RiskAssessment
from .temporal import DriftBudgetEvidence


class EnforcementAction(StrEnum):
    ALLOW = "allow"
    ALLOW_AND_LOG = "allow_and_log"
    REQUIRE_RECONSENT = "require_reconsent"
    QUARANTINE = "quarantine"


class PolicyDecision(BaseModel):
    action: EnforcementAction
    reason: str
    assessment: RiskAssessment | None = None


class DefaultPolicy:
    """Security boundary that converts detector output into an enforcement action."""

    _CLASS_ACTIONS: ClassVar[dict[ChangeClass, EnforcementAction]] = {
        ChangeClass.NO_MEANINGFUL_CHANGE: EnforcementAction.ALLOW,
        ChangeClass.BENIGN_MAINTENANCE: EnforcementAction.ALLOW_AND_LOG,
        ChangeClass.CAPABILITY_EXPANSION: EnforcementAction.REQUIRE_RECONSENT,
        ChangeClass.MALICIOUS_DRIFT: EnforcementAction.QUARANTINE,
    }

    def for_untrusted_tool(self) -> PolicyDecision:
        return PolicyDecision(
            action=EnforcementAction.REQUIRE_RECONSENT,
            reason="No trusted snapshot exists for this tool; explicit approval is required.",
        )

    def decide(self, assessment: RiskAssessment) -> PolicyDecision:
        action = self._CLASS_ACTIONS[assessment.change_class]
        return PolicyDecision(
            action=action,
            reason=f"{assessment.change_class.value} mapped to {action.value} by default policy.",
            assessment=assessment,
        )

    def apply_temporal(
        self,
        decision: PolicyDecision,
        evidence: DriftBudgetEvidence,
    ) -> PolicyDecision:
        """Escalate otherwise-safe drift when the rolling cumulative budget is exceeded."""

        if not evidence.exceeded:
            return decision

        if decision.action not in {
            EnforcementAction.ALLOW,
            EnforcementAction.ALLOW_AND_LOG,
        }:
            return decision

        return PolicyDecision(
            action=EnforcementAction.REQUIRE_RECONSENT,
            reason=(
                "Rolling drift budget exceeded: "
                f"{evidence.cumulative_score:.2f} > {evidence.budget:.2f} "
                f"across {evidence.comparisons} version transitions."
            ),
            assessment=decision.assessment,
        )
