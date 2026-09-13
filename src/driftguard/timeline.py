from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from .checks import RevisionSecurityCheck
from .revisions import DiscoveryRevision, diff_revisions
from .signals import CatalogChangeSignal


class TimelineEventKind(StrEnum):
    CATALOG_SIGNAL = "catalog_signal"
    REVISION = "revision"
    SECURITY_CHECK = "security_check"
    REVIEW = "review"


class TimelineEvent(BaseModel):
    event_id: str
    kind: TimelineEventKind
    occurred_at: datetime
    server_id: str
    summary: str
    revision_id: str | None = None
    tool_name: str | None = None
    severity: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


def _revision_events(revisions: list[DiscoveryRevision]) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []

    for index, revision in enumerate(revisions):
        if index == 0:
            added = sorted({tool.name for tool in revision.tools})
            removed: list[str] = []
            modified: list[str] = []
            changed = bool(added)
        else:
            delta = diff_revisions(revisions[index - 1], revision)
            added = delta.added_tools
            removed = delta.removed_tools
            modified = [item.tool_name for item in delta.modified_tools]
            changed = delta.changed

        events.append(
            TimelineEvent(
                event_id=f"revision:{revision.revision_id}",
                kind=TimelineEventKind.REVISION,
                occurred_at=revision.observed_at,
                server_id=revision.server_id,
                revision_id=revision.revision_id,
                summary=(
                    f"Observed revision via {revision.origin.channel.value} "
                    f"({revision.origin.trigger.value})"
                ),
                details={
                    "tree_hash": revision.tree_hash,
                    "parent_revision_id": revision.parent_revision_id,
                    "channel": revision.origin.channel.value,
                    "trigger": revision.origin.trigger.value,
                    "pending_change_signals": revision.origin.pending_change_signals,
                    "content_changed": changed,
                    "added_tools": added,
                    "removed_tools": removed,
                    "modified_tools": modified,
                },
            )
        )

    return events


def _check_events(checks: list[RevisionSecurityCheck]) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    for check in checks:
        events.append(
            TimelineEvent(
                event_id=f"check:{check.revision_id}",
                kind=TimelineEventKind.SECURITY_CHECK,
                occurred_at=check.checked_at,
                server_id=check.server_id,
                revision_id=check.revision_id,
                severity=check.state.value,
                summary=f"Security check: {check.state.value}",
                details={
                    "detector_name": check.detector_name,
                    "policy_name": check.policy_name,
                    "forwarded_tools": check.forwarded_tools,
                    "withheld_tools": check.withheld_tools,
                },
            )
        )
    return events


def _signal_events(signals: list[CatalogChangeSignal]) -> list[TimelineEvent]:
    return [
        TimelineEvent(
            event_id=f"signal:{signal.signal_id}",
            kind=TimelineEventKind.CATALOG_SIGNAL,
            occurred_at=signal.received_at,
            server_id=signal.server_id,
            revision_id=signal.acknowledged_revision_id,
            severity="pending" if signal.acknowledged_revision_id is None else "acknowledged",
            summary="Server announced a tools-list change",
            details={
                "method": signal.method,
                "acknowledged_revision_id": signal.acknowledged_revision_id,
            },
        )
        for signal in signals
    ]


def _review_events(reviews: list[Any]) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    for index, review in enumerate(reviews):
        event_hash = getattr(review, "event_hash", None)
        fallback = (
            f"{getattr(review, 'tool_name', 'unknown')}:"
            f"{getattr(review, 'sha256', 'unknown')}:"
            f"{getattr(review, 'reviewed_at').isoformat()}:{index}"
        )
        event_id = f"review:{event_hash or fallback}"
        decision = str(getattr(review, "decision"))
        tool_name = str(getattr(review, "tool_name"))
        reviewer = str(getattr(review, "reviewer"))
        reason = getattr(review, "reason", None)

        events.append(
            TimelineEvent(
                event_id=event_id,
                kind=TimelineEventKind.REVIEW,
                occurred_at=getattr(review, "reviewed_at"),
                server_id=str(getattr(review, "server_id")),
                tool_name=tool_name,
                severity=decision,
                summary=f"{decision.capitalize()} {tool_name} by {reviewer}",
                details={
                    "sha256": str(getattr(review, "sha256")),
                    "decision": decision,
                    "reviewer": reviewer,
                    "reason": reason,
                    "event_hash": event_hash,
                },
            )
        )

    return events


def build_server_timeline(
    *,
    revisions: list[DiscoveryRevision],
    checks: list[RevisionSecurityCheck],
    signals: list[CatalogChangeSignal],
    reviews: list[Any],
    newest_first: bool = True,
) -> list[TimelineEvent]:
    """Combine all operator-relevant MCP history into one stable activity feed."""

    events = [
        *_revision_events(revisions),
        *_check_events(checks),
        *_signal_events(signals),
        *_review_events(reviews),
    ]
    events.sort(
        key=lambda item: (item.occurred_at, item.event_id),
        reverse=newest_first,
    )
    return events
