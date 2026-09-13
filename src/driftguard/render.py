from __future__ import annotations

from .blame import ToolBlame
from .changefeed import RevisionChangeEvent
from .revisions import DiscoveryRevision, RevisionDelta, SurfaceObservation


def _short(value: str | None, length: int = 10) -> str:
    return value[:length] if value else "-"


def render_revision_delta(delta: RevisionDelta) -> str:
    lines = [
        f"diff {_short(delta.from_revision_id)}..{_short(delta.to_revision_id)}",
    ]
    for name in delta.added_tools:
        lines.append(f"A  {name}")
    for name in delta.removed_tools:
        lines.append(f"D  {name}")
    for change in delta.modified_tools:
        old_hash = _short(change.old_sha256[0] if change.old_sha256 else None, 8)
        new_hash = _short(change.new_sha256[0] if change.new_sha256 else None, 8)
        lines.append(f"M  {change.tool_name}  {old_hash} -> {new_hash}")
        for field in change.field_changes:
            marker = {"added": "+", "removed": "-", "modified": "~"}[field.kind.value]
            lines.append(f"   {marker} {field.path}")
    for name in delta.duplicate_names_added:
        lines.append(f"!  duplicate tool name introduced: {name}")

    if not delta.changed:
        lines.append("No content changes.")
    return "\n".join(lines)


def render_surface_status(status: SurfaceObservation) -> str:
    revision = status.revision
    lines = [
        f"Server: {revision.server_id}",
        f"Revision: {_short(revision.revision_id, 12)}",
        f"Tree: {_short(revision.tree_hash, 12)}",
    ]

    if status.previous_delta is None:
        lines.extend(["", "Changes since previous revision:", "Initial discovery."])
    else:
        lines.extend(
            ["", "Changes since previous revision:", render_revision_delta(status.previous_delta)]
        )

    trusted = status.trusted_status
    lines.extend(["", "Trusted-state status:"])
    for name in trusted.untrusted_tools:
        lines.append(f"?  {name}  (not approved)")
    for change in trusted.modified_from_trusted:
        lines.append(f"M  {change.tool_name}  (differs from approved version)")
        for field in change.field_changes:
            marker = {"added": "+", "removed": "-", "modified": "~"}[field.kind.value]
            lines.append(f"   {marker} {field.path}")
    for name in trusted.missing_trusted_tools:
        lines.append(f"D  {name}  (approved tool missing from current surface)")
    for name in revision.duplicate_tool_names:
        lines.append(f"!  {name}  (duplicate tool name)")

    if not trusted.review_required:
        lines.append("Current surface matches trusted state.")

    return "\n".join(lines)


def render_revision_log(revisions: list[DiscoveryRevision]) -> str:
    if not revisions:
        return "No revisions."
    lines: list[str] = []
    previous_tree: str | None = None
    for revision in reversed(revisions):
        marker = "=" if previous_tree is not None and revision.tree_hash == previous_tree else "*"
        lines.append(
            f"{marker} {_short(revision.revision_id, 12)}  "
            f"{revision.observed_at.isoformat()}  tree {_short(revision.tree_hash, 12)}"
        )
        previous_tree = revision.tree_hash
    return "\n".join(lines)


def render_change_event(event: RevisionChangeEvent) -> str:
    prefix = "initial" if event.initial else ("changed" if event.content_changed else "unchanged")
    parts = [
        f"{_short(event.revision_id, 12)} {prefix}",
        f"+{len(event.added_tools)}",
        f"~{len(event.modified_tools)}",
        f"-{len(event.removed_tools)}",
    ]
    return "  ".join(parts)


def render_tool_blame(blame: ToolBlame) -> str:
    if blame.ambiguous:
        return (
            f"blame {blame.tool_name}: ambiguous\n"
            f"{blame.ambiguity_reason or 'Provenance cannot be resolved uniquely.'}"
        )

    lines = [
        f"blame {blame.tool_name} @ {_short(blame.target_revision_id, 12)}",
    ]
    for field in blame.fields:
        lines.append(
            f"{_short(field.revision_id, 12)}  "
            f"{field.observed_at.isoformat()}  {field.path}"
        )
    if not blame.fields:
        lines.append("No matching fields.")
    return "\n".join(lines)
