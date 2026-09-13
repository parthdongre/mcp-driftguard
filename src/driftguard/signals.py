from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from pydantic import BaseModel, Field


class CatalogChangeSignal(BaseModel):
    """Persistent record that an MCP server announced its tool catalog changed."""

    signal_id: str
    server_id: str
    received_at: datetime
    method: str = "notifications/tools/list_changed"
    acknowledged_revision_id: str | None = None


class CatalogFreshnessStatus(BaseModel):
    """Whether the latest known catalog may be stale relative to server notification state."""

    dirty: bool
    pending_signals: int = Field(ge=0)
    last_signal_at: datetime | None = None
    last_refreshed_revision_id: str | None = None


def make_catalog_change_signal(
    server_id: str,
    *,
    received_at: datetime | None = None,
) -> CatalogChangeSignal:
    timestamp = received_at or datetime.now(UTC)
    digest = hashlib.sha256(
        f"{server_id}\0{timestamp.isoformat()}\0notifications/tools/list_changed".encode()
    ).hexdigest()
    return CatalogChangeSignal(
        signal_id=digest,
        server_id=server_id,
        received_at=timestamp,
    )


def catalog_freshness(
    signals: list[CatalogChangeSignal],
    *,
    latest_revision_id: str | None,
) -> CatalogFreshnessStatus:
    pending = [signal for signal in signals if signal.acknowledged_revision_id is None]
    return CatalogFreshnessStatus(
        dirty=bool(pending),
        pending_signals=len(pending),
        last_signal_at=signals[-1].received_at if signals else None,
        last_refreshed_revision_id=latest_revision_id,
    )
