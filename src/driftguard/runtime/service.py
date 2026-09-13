from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from ..baselines import rule_baseline
from ..canonicalize import make_snapshot
from ..diff import build_delta
from ..explain import CounterfactualExplanation, greedy_counterfactual
from ..models import RiskAssessment, ToolDelta, ToolSnapshot
from .policy import DefaultPolicy, PolicyDecision
from .store import InMemorySnapshotStore, SnapshotStore
from .temporal import DriftBudget, DriftBudgetEvidence

Detector = Callable[[ToolDelta], RiskAssessment]


class ObservationResult(BaseModel):
    snapshot: ToolSnapshot
    baseline: ToolSnapshot | None = None
    delta: ToolDelta | None = None
    assessment: RiskAssessment | None = None
    temporal: DriftBudgetEvidence | None = None
    counterfactual: CounterfactualExplanation | None = None
    decision: PolicyDecision


class DriftGuardService:
    """Application service that joins snapshots, drift detection, trust, and policy."""

    def __init__(
        self,
        *,
        store: SnapshotStore | None = None,
        detector: Detector = rule_baseline,
        policy: DefaultPolicy | None = None,
        drift_budget: DriftBudget | None = None,
    ) -> None:
        self.store = store if store is not None else InMemorySnapshotStore()
        self.detector = detector
        self.policy = policy if policy is not None else DefaultPolicy()
        self.drift_budget = drift_budget if drift_budget is not None else DriftBudget()

    def observe_tool(
        self,
        *,
        server_id: str,
        tool: dict[str, Any],
        protocol_version: str | None = None,
    ) -> ObservationResult:
        snapshot = make_snapshot(
            server_id=server_id,
            tool=tool,
            protocol_version=protocol_version,
        )
        baseline = self.store.get_trusted(snapshot.server_id, snapshot.tool_name)
        self.store.put_observed(snapshot)
        temporal = self.drift_budget.evaluate(
            self.store.history(snapshot.server_id, snapshot.tool_name),
            self.detector,
        )

        if baseline is None:
            return ObservationResult(
                snapshot=snapshot,
                temporal=temporal,
                decision=self.policy.for_untrusted_tool(),
            )

        delta = build_delta(baseline, snapshot)
        assessment = self.detector(delta)
        decision = self.policy.apply_temporal(self.policy.decide(assessment), temporal)
        return ObservationResult(
            snapshot=snapshot,
            baseline=baseline,
            delta=delta,
            assessment=assessment,
            temporal=temporal,
            counterfactual=greedy_counterfactual(assessment),
            decision=decision,
        )

    def approve(self, snapshot: ToolSnapshot) -> ToolSnapshot:
        """Promote one reviewed observation to the trusted comparison baseline."""

        approved = snapshot.model_copy(update={"approval_state": "approved"})
        self.store.trust(approved)
        return approved
