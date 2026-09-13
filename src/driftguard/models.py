from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ChangeClass(StrEnum):
    """Operational classes used by the version-pair classifier."""

    NO_MEANINGFUL_CHANGE = "C0"
    BENIGN_MAINTENANCE = "C1"
    CAPABILITY_EXPANSION = "C2"
    MALICIOUS_DRIFT = "C3"


class ToolSnapshot(BaseModel):
    """One observed version of an MCP tool definition."""

    server_id: str
    tool_name: str
    raw_tool: dict[str, Any]
    canonical_tool: dict[str, Any]
    sha256: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    protocol_version: str | None = None
    approval_state: str = "unreviewed"
    parent_snapshot_id: str | None = None


class StructuralDelta(BaseModel):
    """Typed, security-relevant changes between two tool definitions."""

    parameters_added: list[str] = Field(default_factory=list)
    parameters_removed: list[str] = Field(default_factory=list)
    required_added: list[str] = Field(default_factory=list)
    required_removed: list[str] = Field(default_factory=list)
    type_changes: dict[str, tuple[str | None, str | None]] = Field(default_factory=dict)
    default_changes: dict[str, tuple[Any, Any]] = Field(default_factory=dict)
    enum_changes: list[str] = Field(default_factory=list)
    sensitive_terms_added: list[str] = Field(default_factory=list)
    urls_added: list[str] = Field(default_factory=list)
    cross_tool_references_added: list[str] = Field(default_factory=list)
    imperative_terms_added: list[str] = Field(default_factory=list)


class ToolDelta(BaseModel):
    """Pairwise change object passed to feature extraction / classification."""

    old: ToolSnapshot
    new: ToolSnapshot
    structural: StructuralDelta
    changed_fields: list[str] = Field(default_factory=list)
    lexical_change_ratio: float = 0.0


class RiskContribution(BaseModel):
    """One named contribution to an explainable detector score."""

    signal: str
    points: float = Field(ge=0.0)
    evidence: list[str] = Field(default_factory=list)


class RiskAssessment(BaseModel):
    """Model-agnostic assessment returned by the detector pipeline."""

    change_class: ChangeClass
    risk_score: float = Field(ge=0.0, le=100.0)
    reasons: list[str] = Field(default_factory=list)
    recommended_action: str
    probabilities: dict[str, float] = Field(default_factory=dict)
    contributions: list[RiskContribution] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    abstained: bool = False
    uncertainty_reason: str | None = None
