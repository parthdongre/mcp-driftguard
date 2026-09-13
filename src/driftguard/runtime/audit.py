from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ReviewDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class ReviewEvent(BaseModel):
    """Append-only human review record for one observed tool snapshot."""

    server_id: str
    tool_name: str
    sha256: str
    decision: ReviewDecision
    reviewer: str
    reason: str | None = None
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    previous_event_hash: str | None = None
    event_hash: str | None = None


class AuditIntegrityReport(BaseModel):
    """Result of independently verifying one tool's review-event hash chain."""

    valid: bool
    event_count: int = Field(ge=0)
    head_hash: str | None = None
    first_invalid_index: int | None = Field(default=None, ge=0)
    reason: str | None = None


def _hashable_payload(event: ReviewEvent) -> bytes:
    payload = event.model_dump(mode="json", exclude={"event_hash"})
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return serialized.encode("utf-8")


def compute_review_hash(event: ReviewEvent) -> str:
    """Compute the deterministic SHA-256 digest for a sealed review event."""

    return hashlib.sha256(_hashable_payload(event)).hexdigest()


def seal_review_event(
    event: ReviewEvent,
    *,
    previous_event_hash: str | None,
) -> ReviewEvent:
    """Attach the previous digest and seal a review event with its own digest."""

    chained = event.model_copy(
        update={
            "previous_event_hash": previous_event_hash,
            "event_hash": None,
        }
    )
    return chained.model_copy(update={"event_hash": compute_review_hash(chained)})


def verify_review_chain(events: list[ReviewEvent]) -> AuditIntegrityReport:
    """Verify ordering, linkage, and content integrity for an append-only review chain."""

    expected_previous: str | None = None

    for index, event in enumerate(events):
        if event.event_hash is None:
            return AuditIntegrityReport(
                valid=False,
                event_count=len(events),
                head_hash=events[-1].event_hash if events else None,
                first_invalid_index=index,
                reason="Review event is not hash-sealed.",
            )

        if event.previous_event_hash != expected_previous:
            return AuditIntegrityReport(
                valid=False,
                event_count=len(events),
                head_hash=events[-1].event_hash,
                first_invalid_index=index,
                reason="Review-event chain linkage is broken.",
            )

        expected_hash = compute_review_hash(event)
        if event.event_hash != expected_hash:
            return AuditIntegrityReport(
                valid=False,
                event_count=len(events),
                head_hash=events[-1].event_hash,
                first_invalid_index=index,
                reason="Review-event content does not match its recorded hash.",
            )

        expected_previous = event.event_hash

    return AuditIntegrityReport(
        valid=True,
        event_count=len(events),
        head_hash=expected_previous,
    )
