from __future__ import annotations

from pydantic import BaseModel, Field

from .checkpoints import TrustedCheckpoint
from .checks import RevisionSecurityCheck
from .models import ToolSnapshot
from .revisions import (
    DiscoveryRevision,
    RevisionDelta,
    TrustedSurfaceStatus,
    compare_to_trusted,
    diff_revisions,
)
from .signals import CatalogFreshnessStatus


class ServerOverview(BaseModel):
    """Repository-style summary for one MCP server."""

    server_id: str
    latest_revision: DiscoveryRevision
    latest_security_check: RevisionSecurityCheck | None = None
    freshness: CatalogFreshnessStatus
    trusted_status: TrustedSurfaceStatus
    tool_count: int = Field(ge=0)
    latest_checkpoint: TrustedCheckpoint | None = None
    checkpoint_delta: RevisionDelta | None = None
    revisions_since_checkpoint: int | None = Field(default=None, ge=0)
    checkpoint_tree_matches: bool | None = None


def build_server_overview(
    *,
    revisions: list[DiscoveryRevision],
    checks: list[RevisionSecurityCheck],
    checkpoints: list[TrustedCheckpoint],
    freshness: CatalogFreshnessStatus,
    trusted_snapshots: list[ToolSnapshot],
) -> ServerOverview | None:
    if not revisions:
        return None

    latest = revisions[-1]
    check_by_revision = {check.revision_id: check for check in checks}
    latest_check = check_by_revision.get(latest.revision_id)
    trusted_status = compare_to_trusted(latest, trusted_snapshots)

    latest_checkpoint = max(
        checkpoints,
        key=lambda item: item.created_at,
        default=None,
    )
    checkpoint_delta: RevisionDelta | None = None
    revisions_since_checkpoint: int | None = None
    checkpoint_tree_matches: bool | None = None

    if latest_checkpoint is not None:
        checkpoint_index = next(
            (
                index
                for index, revision in enumerate(revisions)
                if revision.revision_id == latest_checkpoint.revision_id
            ),
            None,
        )
        if checkpoint_index is not None:
            checkpoint_revision = revisions[checkpoint_index]
            checkpoint_delta = diff_revisions(checkpoint_revision, latest)
            revisions_since_checkpoint = len(revisions) - checkpoint_index - 1
            checkpoint_tree_matches = checkpoint_revision.tree_hash == latest.tree_hash

    return ServerOverview(
        server_id=latest.server_id,
        latest_revision=latest,
        latest_security_check=latest_check,
        freshness=freshness,
        trusted_status=trusted_status,
        tool_count=len(latest.tools),
        latest_checkpoint=latest_checkpoint,
        checkpoint_delta=checkpoint_delta,
        revisions_since_checkpoint=revisions_since_checkpoint,
        checkpoint_tree_matches=checkpoint_tree_matches,
    )
