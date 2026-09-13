from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator


class TrustedCheckpoint(BaseModel):
    """Named immutable reference to a revision that passed its security check."""

    checkpoint_id: str
    server_id: str
    name: str
    revision_id: str
    tree_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_by: str
    note: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("Checkpoint name must not be empty.")
        if len(clean) > 100:
            raise ValueError("Checkpoint name must be at most 100 characters.")
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-/")
        if any(char not in allowed for char in clean):
            raise ValueError(
                "Checkpoint names may contain letters, digits, '.', '_', '-', and '/'."
            )
        return clean


def make_checkpoint(
    *,
    server_id: str,
    name: str,
    revision_id: str,
    tree_hash: str,
    created_by: str,
    note: str | None = None,
    created_at: datetime | None = None,
) -> TrustedCheckpoint:
    timestamp = created_at or datetime.now(UTC)
    clean_name = name.strip()
    checkpoint_id = hashlib.sha256(
        (
            f"{server_id}\0{clean_name}\0{revision_id}\0"
            f"{tree_hash}\0{timestamp.isoformat()}\0{created_by}"
        ).encode()
    ).hexdigest()
    return TrustedCheckpoint(
        checkpoint_id=checkpoint_id,
        server_id=server_id,
        name=clean_name,
        revision_id=revision_id,
        tree_hash=tree_hash,
        created_at=timestamp,
        created_by=created_by,
        note=note,
    )
