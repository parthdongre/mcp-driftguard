from __future__ import annotations

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
