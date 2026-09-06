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


class SemanticViews(BaseModel):
    """Field-aware textual views used by the future embedding pipeline."""

    purpose: str
    input_contract: str
    output_contract: str
    capability_safety: str
    full_schema: str


class CapabilityProfile(BaseModel):
    """A deterministic approximation of the effective capability surface of a tool.

    This is deliberately an interpretable intermediate representation. Later learned
    models can consume it as structured features without treating it as ground truth.
    """

    operations: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    effects: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    destinations: list[str] = Field(default_factory=list)
    sensitivity: list[str] = Field(default_factory=list)
    evidence: dict[str, list[str]] = Field(default_factory=dict)


class CapabilityDelta(BaseModel):
    """Added/removed effective-capability signals between two tool versions."""

    operations_added: list[str] = Field(default_factory=list)
    operations_removed: list[str] = Field(default_factory=list)
    resources_added: list[str] = Field(default_factory=list)
    resources_removed: list[str] = Field(default_factory=list)
    effects_added: list[str] = Field(default_factory=list)
    effects_removed: list[str] = Field(default_factory=list)
    scopes_added: list[str] = Field(default_factory=list)
    scopes_removed: list[str] = Field(default_factory=list)
    destinations_added: list[str] = Field(default_factory=list)
    destinations_removed: list[str] = Field(default_factory=list)
    sensitivity_added: list[str] = Field(default_factory=list)
    sensitivity_removed: list[str] = Field(default_factory=list)


class PairFeatures(BaseModel):
    """Model-ready deterministic features for one old/new schema pair."""

    view_lexical_drift: dict[str, float] = Field(default_factory=dict)
    structural_counts: dict[str, float] = Field(default_factory=dict)
    capability_delta: CapabilityDelta
    capability_escalation_score: float = Field(ge=0.0, le=1.0)
    lexical_change_ratio: float = Field(ge=0.0, le=1.0)


class TemporalAssessment(BaseModel):
    """Stateful assessment for a version sequence of one tool."""

    tool_name: str
    versions_seen: int
    step_risk: float = Field(ge=0.0, le=1.0)
    baseline_risk: float = Field(ge=0.0, le=1.0)
    cusum_score: float = Field(ge=0.0)
    alerted: bool
    reasons: list[str] = Field(default_factory=list)


class RiskAssessment(BaseModel):
    """Model-agnostic assessment returned by the detector pipeline."""

    change_class: ChangeClass
    risk_score: float = Field(ge=0.0, le=100.0)
    reasons: list[str] = Field(default_factory=list)
    recommended_action: str
    probabilities: dict[str, float] = Field(default_factory=dict)
