from __future__ import annotations

from pydantic import BaseModel

from .checks import RevisionSecurityCheck
from .revisions import DiscoveryRevision, RevisionDelta
from .signals import CatalogFreshnessStatus


class RevisionView(BaseModel):
    """Git-show-style aggregate for one immutable MCP discovery revision."""

    revision: DiscoveryRevision
    parent_delta: RevisionDelta | None = None
    security_check: RevisionSecurityCheck | None = None
    is_latest: bool = False
    freshness: CatalogFreshnessStatus | None = None


def build_revision_view(
    revisions: list[DiscoveryRevision],
    *,
    target_revision_id: str,
    security_check: RevisionSecurityCheck | None = None,
    freshness: CatalogFreshnessStatus | None = None,
) -> RevisionView | None:
    from .revisions import diff_revisions

    target_index: int | None = None
    for index, revision in enumerate(revisions):
        if revision.revision_id == target_revision_id:
            target_index = index
            break

    if target_index is None:
        return None

    target = revisions[target_index]
    parent_delta = None
    if target_index > 0:
        parent_delta = diff_revisions(revisions[target_index - 1], target)

    is_latest = target_index == len(revisions) - 1
    return RevisionView(
        revision=target,
        parent_delta=parent_delta,
        security_check=security_check,
        is_latest=is_latest,
        freshness=freshness if is_latest else None,
    )
