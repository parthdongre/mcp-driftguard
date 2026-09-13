from __future__ import annotations

from .blame import ToolBlame
from .changefeed import RevisionChangeEvent
from .checks import RevisionSecurityCheck
from .revisions import DiscoveryRevision, RevisionDelta, SurfaceObservation
from .signals import CatalogFreshnessStatus
from .views import RevisionView


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
    if status.freshness is not None:
        state = "DIRTY" if status.freshness.dirty else "clean"
        lines.append(
            f"Catalog: {state} ({status.freshness.pending_signals} pending refresh signal(s))"
        )

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
            f"{revision.observed_at.isoformat()}  "
            f"{revision.origin.channel.value}/{revision.origin.trigger.value}  "
            f"tree {_short(revision.tree_hash, 12)}"
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


def render_catalog_freshness(freshness: CatalogFreshnessStatus) -> str:
    state = "DIRTY" if freshness.dirty else "clean"
    lines = [
        f"Catalog: {state}",
        f"Pending change signals: {freshness.pending_signals}",
        f"Last refreshed revision: {_short(freshness.last_refreshed_revision_id, 12)}",
    ]
    if freshness.last_signal_at is not None:
        lines.append(f"Last change notification: {freshness.last_signal_at.isoformat()}")
    return "\n".join(lines)


def render_revision_check(check: RevisionSecurityCheck) -> str:
    lines = [
        f"check {_short(check.revision_id, 12)}: {check.state.value}",
        f"detector: {check.detector_name}",
        f"policy: {check.policy_name}",
        f"forwarded: {len(check.forwarded_tools)}  withheld: {len(check.withheld_tools)}",
    ]
    for tool in check.tools:
        risk = "-" if tool.risk_score is None else f"{tool.risk_score:.2f}"
        klass = tool.change_class or "-"
        lines.append(
            f"{tool.action:18}  {tool.tool_name}  class={klass}  risk={risk}"
        )
        if tool.temporal_exceeded:
            lines.append(
                f"  ! temporal budget exceeded ({tool.temporal_cumulative_score:.2f})"
            )
    return "\n".join(lines)


def render_revision_view(view: RevisionView) -> str:
    revision = view.revision
    lines = [
        f"revision {_short(revision.revision_id, 12)}",
        f"server: {revision.server_id}",
        f"tree: {_short(revision.tree_hash, 12)}",
        f"observed: {revision.observed_at.isoformat()}",
        f"parent: {_short(revision.parent_revision_id, 12)}",
        f"origin: {revision.origin.channel.value} / {revision.origin.trigger.value}",
    ]
    if revision.origin.pending_change_signals:
        lines.append(
            f"refresh signals: {revision.origin.pending_change_signals}"
        )

    if view.is_latest and view.freshness is not None:
        state = "DIRTY" if view.freshness.dirty else "clean"
        lines.append(
            f"catalog: {state} ({view.freshness.pending_signals} pending signal(s))"
        )

    lines.extend(["", "Changes from parent:"])
    if view.parent_delta is None:
        lines.append("Initial discovery revision.")
    else:
        lines.append(render_revision_delta(view.parent_delta))

    lines.extend(["", "Security check:"])
    if view.security_check is None:
        lines.append("No persisted security check.")
    else:
        lines.append(render_revision_check(view.security_check))

    return "\n".join(lines)
