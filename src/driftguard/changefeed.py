from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .revisions import DiscoveryRevision, ToolRevisionChange, diff_revisions


class RevisionChangeEvent(BaseModel):
    """Compact feed item suitable for polling, UI timelines, and CLI watch mode."""

    revision_id: str
    parent_revision_id: str | None = None
    tree_hash: str
    observed_at: datetime
    initial: bool = False
    content_changed: bool
    added_tools: list[str] = Field(default_factory=list)
    removed_tools: list[str] = Field(default_factory=list)
    modified_tools: list[ToolRevisionChange] = Field(default_factory=list)
    duplicate_names_added: list[str] = Field(default_factory=list)


def build_change_feed(revisions: list[DiscoveryRevision]) -> list[RevisionChangeEvent]:
    """Build chronological change events from immutable discovery revisions."""

    events: list[RevisionChangeEvent] = []
    for index, revision in enumerate(revisions):
        if index == 0:
            names = sorted({tool.name for tool in revision.tools})
            events.append(
                RevisionChangeEvent(
                    revision_id=revision.revision_id,
                    parent_revision_id=None,
                    tree_hash=revision.tree_hash,
                    observed_at=revision.observed_at,
                    initial=True,
                    content_changed=bool(revision.tools or revision.duplicate_tool_names),
                    added_tools=names,
                    duplicate_names_added=revision.duplicate_tool_names,
                )
            )
            continue

        previous = revisions[index - 1]
        delta = diff_revisions(previous, revision)
        events.append(
            RevisionChangeEvent(
                revision_id=revision.revision_id,
                parent_revision_id=revision.parent_revision_id,
                tree_hash=revision.tree_hash,
                observed_at=revision.observed_at,
                content_changed=delta.changed,
                added_tools=delta.added_tools,
                removed_tools=delta.removed_tools,
                modified_tools=delta.modified_tools,
                duplicate_names_added=delta.duplicate_names_added,
            )
        )
    return events


def changes_after(
    revisions: list[DiscoveryRevision],
    revision_id: str | None,
) -> list[RevisionChangeEvent] | None:
    """Return feed events after a known revision; None means the cursor is unknown."""

    events = build_change_feed(revisions)
    if revision_id is None:
        return events
    for index, event in enumerate(events):
        if event.revision_id == revision_id:
            return events[index + 1 :]
    return None
