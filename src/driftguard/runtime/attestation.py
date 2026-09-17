from __future__ import annotations

import hashlib
import json
from collections import defaultdict

from pydantic import BaseModel, Field

from ..checkpoints import TrustedCheckpoint
from ..checks import RevisionSecurityCheck
from ..models import ToolSnapshot
from ..revisions import DiscoveryRevision
from ..signals import CatalogFreshnessStatus
from .audit import ReviewEvent


ATTESTATION_SCHEMA_VERSION = "driftguard.trust-attestation.v1"


class TrustAttestation(BaseModel):
    """Deterministic digest over the durable trust state for one MCP server."""

    schema_version: str = ATTESTATION_SCHEMA_VERSION
    server_id: str
    revision_id: str
    tree_hash: str
    security_state: str | None = None
    checkpoint_ids: list[str] = Field(default_factory=list)
    trusted_tool_hashes: dict[str, str] = Field(default_factory=dict)
    review_heads: dict[str, str] = Field(default_factory=dict)
    review_event_counts: dict[str, int] = Field(default_factory=dict)
    catalog_dirty: bool
    pending_change_signals: int = Field(ge=0)
    attestation_hash: str


def _canonical_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def build_trust_attestation(
    *,
    revision: DiscoveryRevision,
    security_check: RevisionSecurityCheck | None,
    checkpoints: list[TrustedCheckpoint],
    trusted_snapshots: list[ToolSnapshot],
    reviews: list[ReviewEvent],
    freshness: CatalogFreshnessStatus,
) -> TrustAttestation:
    """Build a stable hash that can later be externally signed or anchored."""

    review_heads: dict[str, str] = {}
    review_event_counts: dict[str, int] = defaultdict(int)
    for event in reviews:
        review_event_counts[event.tool_name] += 1
        if event.event_hash is not None:
            review_heads[event.tool_name] = event.event_hash

    payload: dict[str, object] = {
        "schema_version": ATTESTATION_SCHEMA_VERSION,
        "server_id": revision.server_id,
        "revision_id": revision.revision_id,
        "tree_hash": revision.tree_hash,
        "security_state": security_check.state.value if security_check is not None else None,
        "checkpoint_ids": sorted(checkpoint.checkpoint_id for checkpoint in checkpoints),
        "trusted_tool_hashes": {
            snapshot.tool_name: snapshot.sha256
            for snapshot in sorted(trusted_snapshots, key=lambda item: item.tool_name)
        },
        "review_heads": dict(sorted(review_heads.items())),
        "review_event_counts": dict(sorted(review_event_counts.items())),
        "catalog_dirty": freshness.dirty,
        "pending_change_signals": freshness.pending_signals,
    }
    attestation_hash = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return TrustAttestation(**payload, attestation_hash=attestation_hash)
