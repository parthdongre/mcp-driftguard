from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from .revisions import DiscoveryRevision


class RevisionCheckState(StrEnum):
    PASS = "pass"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"


class ToolSecurityCheck(BaseModel):
    tool_name: str
    sha256: str
    action: str
    reason: str
    change_class: str | None = None
    risk_score: float | None = Field(default=None, ge=0.0, le=100.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    abstained: bool = False
    temporal_cumulative_score: float | None = Field(default=None, ge=0.0)
    temporal_exceeded: bool = False


class RevisionSecurityCheck(BaseModel):
    """Immutable security verdict attached to one discovery revision."""

    server_id: str
    revision_id: str
    tree_hash: str
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    state: RevisionCheckState
    detector_name: str
    policy_name: str
    forwarded_tools: list[str] = Field(default_factory=list)
    withheld_tools: list[str] = Field(default_factory=list)
    tools: list[ToolSecurityCheck] = Field(default_factory=list)


def _component_name(component: Any) -> str:
    name = getattr(component, "__name__", None)
    if isinstance(name, str):
        return name
    return type(component).__name__


def build_revision_check(
    *,
    revision: DiscoveryRevision,
    observations: list[Any],
    forwarded_tools: list[str],
    withheld_tools: list[str],
    detector: Any,
    policy: Any,
) -> RevisionSecurityCheck:
    """Snapshot operational verdicts without importing runtime service classes."""

    tool_checks: list[ToolSecurityCheck] = []
    actions: set[str] = set()

    for observation in observations:
        action = str(observation.decision.action)
        actions.add(action)
        assessment = observation.assessment
        temporal = observation.temporal

        tool_checks.append(
            ToolSecurityCheck(
                tool_name=observation.snapshot.tool_name,
                sha256=observation.snapshot.sha256,
                action=action,
                reason=observation.decision.reason,
                change_class=(
                    assessment.change_class.value
                    if assessment is not None
                    else None
                ),
                risk_score=assessment.risk_score if assessment is not None else None,
                confidence=assessment.confidence if assessment is not None else None,
                abstained=assessment.abstained if assessment is not None else False,
                temporal_cumulative_score=(
                    temporal.cumulative_score if temporal is not None else None
                ),
                temporal_exceeded=temporal.exceeded if temporal is not None else False,
            )
        )

    if "quarantine" in actions:
        state = RevisionCheckState.BLOCKED
    elif "require_reconsent" in actions or withheld_tools:
        state = RevisionCheckState.REVIEW_REQUIRED
    else:
        state = RevisionCheckState.PASS

    return RevisionSecurityCheck(
        server_id=revision.server_id,
        revision_id=revision.revision_id,
        tree_hash=revision.tree_hash,
        state=state,
        detector_name=_component_name(detector),
        policy_name=_component_name(policy),
        forwarded_tools=forwarded_tools,
        withheld_tools=withheld_tools,
        tools=tool_checks,
    )
