from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from ..baselines import rule_baseline
from ..canonicalize import make_snapshot
from ..changefeed import RevisionChangeEvent, changes_after
from ..diff import build_delta
from ..explain import CounterfactualExplanation, greedy_counterfactual
from ..models import RiskAssessment, ToolDelta, ToolSnapshot
from ..revisions import (
    DiscoveryRevision,
    RevisionDelta,
    SurfaceObservation,
    compare_to_trusted,
    diff_revisions,
    make_discovery_revision,
)
from .audit import ReviewDecision, ReviewEvent, seal_review_event
from .policy import DefaultPolicy, PolicyDecision
from .store import InMemorySnapshotStore, SnapshotStore
from .temporal import DriftBudget, DriftBudgetEvidence

Detector = Callable[[ToolDelta], RiskAssessment]
Explainer = Callable[[RiskAssessment], CounterfactualExplanation]


class ObservationResult(BaseModel):
    snapshot: ToolSnapshot
    baseline: ToolSnapshot | None = None
    delta: ToolDelta | None = None
    assessment: RiskAssessment | None = None
    temporal: DriftBudgetEvidence | None = None
    counterfactual: CounterfactualExplanation | None = None
    decision: PolicyDecision


class DriftGuardService:
    """Application service that joins snapshots, revisions, detection, trust, and policy."""

    def __init__(
        self,
        *,
        store: SnapshotStore | None = None,
        detector: Detector = rule_baseline,
        policy: DefaultPolicy | None = None,
        drift_budget: DriftBudget | None = None,
        explainer: Explainer | None = None,
    ) -> None:
        self.store = store if store is not None else InMemorySnapshotStore()
        self.detector = detector
        self.policy = policy if policy is not None else DefaultPolicy()
        self.drift_budget = drift_budget if drift_budget is not None else DriftBudget()
        self.explainer = (
            explainer
            if explainer is not None
            else (greedy_counterfactual if detector is rule_baseline else None)
        )

    def observe_surface(
        self,
        *,
        server_id: str,
        tools: list[dict[str, Any]],
        protocol_version: str | None = None,
    ) -> SurfaceObservation:
        """Commit one complete discovery surface and compute Git-like status."""

        previous = self.store.latest_revision(server_id)
        revision = make_discovery_revision(
            server_id=server_id,
            tools=tools,
            parent_revision_id=previous.revision_id if previous is not None else None,
            protocol_version=protocol_version,
        )
        self.store.put_revision(revision)
        previous_delta = diff_revisions(previous, revision) if previous is not None else None
        trusted_status = compare_to_trusted(
            revision,
            self.store.trusted_tools(server_id),
        )
        return SurfaceObservation(
            revision=revision,
            previous_delta=previous_delta,
            trusted_status=trusted_status,
        )

    def current_surface_status(self, server_id: str) -> SurfaceObservation | None:
        """Return current status without creating a new revision."""

        history = self.store.revision_history(server_id)
        if not history:
            return None
        revision = history[-1]
        previous = history[-2] if len(history) > 1 else None
        return SurfaceObservation(
            revision=revision,
            previous_delta=diff_revisions(previous, revision) if previous is not None else None,
            trusted_status=compare_to_trusted(
                revision,
                self.store.trusted_tools(server_id),
            ),
        )

    def revision_history(self, server_id: str) -> list[DiscoveryRevision]:
        return self.store.revision_history(server_id)

    def change_feed(
        self,
        server_id: str,
        *,
        after_revision_id: str | None = None,
    ) -> list[RevisionChangeEvent] | None:
        return changes_after(
            self.store.revision_history(server_id),
            after_revision_id,
        )

    def get_revision(self, server_id: str, revision_id: str) -> DiscoveryRevision | None:
        return self.store.get_revision(server_id, revision_id)

    def compare_revisions(
        self,
        *,
        server_id: str,
        from_revision_id: str,
        to_revision_id: str,
    ) -> RevisionDelta | None:
        old = self.store.get_revision(server_id, from_revision_id)
        new = self.store.get_revision(server_id, to_revision_id)
        if old is None or new is None:
            return None
        return diff_revisions(old, new)

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
            counterfactual=self.explainer(assessment) if self.explainer is not None else None,
            decision=decision,
        )

    def get_observed(
        self,
        *,
        server_id: str,
        tool_name: str,
        sha256: str,
    ) -> ToolSnapshot | None:
        return self.store.get_observed(server_id, tool_name, sha256)

    def _record_review(
        self,
        *,
        snapshot: ToolSnapshot,
        decision: ReviewDecision,
        reviewer: str,
        reason: str | None,
    ) -> ReviewEvent:
        history = self.store.reviews(snapshot.server_id, snapshot.tool_name)
        previous_hash = history[-1].event_hash if history else None
        event = seal_review_event(
            ReviewEvent(
                server_id=snapshot.server_id,
                tool_name=snapshot.tool_name,
                sha256=snapshot.sha256,
                decision=decision,
                reviewer=reviewer,
                reason=reason,
            ),
            previous_event_hash=previous_hash,
        )
        self.store.record_review(event)
        return event

    def approve(
        self,
        snapshot: ToolSnapshot,
        *,
        reviewer: str = "local-reviewer",
        reason: str | None = None,
    ) -> ToolSnapshot:
        approved = snapshot.model_copy(update={"approval_state": "approved"})
        self._record_review(
            snapshot=approved,
            decision=ReviewDecision.APPROVED,
            reviewer=reviewer,
            reason=reason,
        )
        self.store.trust(approved)
        return approved

    def reject(
        self,
        snapshot: ToolSnapshot,
        *,
        reviewer: str = "local-reviewer",
        reason: str | None = None,
    ) -> ToolSnapshot:
        rejected = snapshot.model_copy(update={"approval_state": "rejected"})
        self._record_review(
            snapshot=rejected,
            decision=ReviewDecision.REJECTED,
            reviewer=reviewer,
            reason=reason,
        )
        return rejected
