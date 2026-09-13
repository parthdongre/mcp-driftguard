from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from .canonicalize import canonicalize_tool, schema_hash
from .models import ToolSnapshot


class RevisionTool(BaseModel):
    name: str
    sha256: str
    canonical_tool: dict[str, Any]


class DiscoveryRevision(BaseModel):
    """Git-like immutable observation of an entire MCP tools/list surface."""

    server_id: str
    revision_id: str
    tree_hash: str
    observed_at: datetime
    parent_revision_id: str | None = None
    protocol_version: str | None = None
    tools: list[RevisionTool] = Field(default_factory=list)
    duplicate_tool_names: list[str] = Field(default_factory=list)


class FieldChangeKind(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"


class JsonFieldChange(BaseModel):
    """One exact JSON-pointer path changed inside a tool definition."""

    path: str
    kind: FieldChangeKind


class ToolRevisionChange(BaseModel):
    tool_name: str
    old_sha256: list[str] = Field(default_factory=list)
    new_sha256: list[str] = Field(default_factory=list)
    field_changes: list[JsonFieldChange] = Field(default_factory=list)


class RevisionDelta(BaseModel):
    from_revision_id: str
    to_revision_id: str
    added_tools: list[str] = Field(default_factory=list)
    removed_tools: list[str] = Field(default_factory=list)
    modified_tools: list[ToolRevisionChange] = Field(default_factory=list)
    unchanged_tools: list[str] = Field(default_factory=list)
    duplicate_names_added: list[str] = Field(default_factory=list)
    duplicate_names_resolved: list[str] = Field(default_factory=list)
    changed: bool = False


class TrustedSurfaceStatus(BaseModel):
    """Difference between the latest observed surface and per-tool trusted baselines."""

    revision_id: str
    untrusted_tools: list[str] = Field(default_factory=list)
    missing_trusted_tools: list[str] = Field(default_factory=list)
    modified_from_trusted: list[ToolRevisionChange] = Field(default_factory=list)
    unchanged_trusted_tools: list[str] = Field(default_factory=list)
    review_required: bool = False


class SurfaceObservation(BaseModel):
    """Status object returned whenever a complete MCP discovery surface is observed."""

    revision: DiscoveryRevision
    previous_delta: RevisionDelta | None = None
    trusted_status: TrustedSurfaceStatus


def _surface_tool_entries(tools: list[dict[str, Any]]) -> list[RevisionTool]:
    entries: list[RevisionTool] = []
    for index, tool in enumerate(tools):
        canonical = canonicalize_tool(tool)
        raw_name = canonical.get("name")
        name = str(raw_name) if raw_name else f"unknown-tool-{index}"
        entries.append(
            RevisionTool(
                name=name,
                sha256=schema_hash(canonical),
                canonical_tool=canonical,
            )
        )
    return sorted(entries, key=lambda item: (item.name, item.sha256))


def _hash_payload(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def make_discovery_revision(
    *,
    server_id: str,
    tools: list[dict[str, Any]],
    parent_revision_id: str | None = None,
    protocol_version: str | None = None,
    observed_at: datetime | None = None,
) -> DiscoveryRevision:
    """Create a commit-like revision for one full tools/list observation."""

    timestamp = observed_at or datetime.now(UTC)
    entries = _surface_tool_entries(tools)
    counts = Counter(entry.name for entry in entries)
    duplicates = sorted(name for name, count in counts.items() if count > 1)

    tree_payload = [
        {
            "name": entry.name,
            "sha256": entry.sha256,
            "canonical_tool": entry.canonical_tool,
        }
        for entry in entries
    ]
    tree_hash = _hash_payload(tree_payload)
    revision_id = _hash_payload(
        {
            "server_id": server_id,
            "tree_hash": tree_hash,
            "parent_revision_id": parent_revision_id,
            "protocol_version": protocol_version,
            "observed_at": timestamp.isoformat(),
        }
    )

    return DiscoveryRevision(
        server_id=server_id,
        revision_id=revision_id,
        tree_hash=tree_hash,
        observed_at=timestamp,
        parent_revision_id=parent_revision_id,
        protocol_version=protocol_version,
        tools=entries,
        duplicate_tool_names=duplicates,
    )


def _hashes_by_name(revision: DiscoveryRevision) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for tool in revision.tools:
        grouped.setdefault(tool.name, []).append(tool.sha256)
    return {name: sorted(hashes) for name, hashes in grouped.items()}


def _tools_by_name(revision: DiscoveryRevision) -> dict[str, list[RevisionTool]]:
    grouped: dict[str, list[RevisionTool]] = {}
    for tool in revision.tools:
        grouped.setdefault(tool.name, []).append(tool)
    return grouped


def _pointer_segment(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _child_path(parent: str, key: str) -> str:
    segment = _pointer_segment(key)
    return f"{parent}/{segment}" if parent else f"/{segment}"


def _diff_json(old: Any, new: Any, path: str = "") -> list[JsonFieldChange]:
    """Return concise field paths; arrays are treated atomically to keep diffs stable."""

    if isinstance(old, dict) and isinstance(new, dict):
        changes: list[JsonFieldChange] = []
        old_keys = set(old)
        new_keys = set(new)

        for key in sorted(new_keys - old_keys):
            changes.append(
                JsonFieldChange(
                    path=_child_path(path, key),
                    kind=FieldChangeKind.ADDED,
                )
            )
        for key in sorted(old_keys - new_keys):
            changes.append(
                JsonFieldChange(
                    path=_child_path(path, key),
                    kind=FieldChangeKind.REMOVED,
                )
            )
        for key in sorted(old_keys & new_keys):
            changes.extend(
                _diff_json(
                    old[key],
                    new[key],
                    _child_path(path, key),
                )
            )
        return changes

    if old == new:
        return []

    return [
        JsonFieldChange(
            path=path or "/",
            kind=FieldChangeKind.MODIFIED,
        )
    ]


def _field_changes_for_unique_tools(
    old_tools: list[RevisionTool],
    new_tools: list[RevisionTool],
) -> list[JsonFieldChange]:
    if len(old_tools) != 1 or len(new_tools) != 1:
        return []
    return _diff_json(old_tools[0].canonical_tool, new_tools[0].canonical_tool)


def diff_revisions(old: DiscoveryRevision, new: DiscoveryRevision) -> RevisionDelta:
    """Compare two full discovery revisions similarly to a repository tree diff."""

    old_map = _hashes_by_name(old)
    new_map = _hashes_by_name(new)
    old_tools = _tools_by_name(old)
    new_tools = _tools_by_name(new)
    old_names = set(old_map)
    new_names = set(new_map)

    added = sorted(new_names - old_names)
    removed = sorted(old_names - new_names)
    unchanged: list[str] = []
    modified: list[ToolRevisionChange] = []

    for name in sorted(old_names & new_names):
        if old_map[name] == new_map[name]:
            unchanged.append(name)
        else:
            modified.append(
                ToolRevisionChange(
                    tool_name=name,
                    old_sha256=old_map[name],
                    new_sha256=new_map[name],
                    field_changes=_field_changes_for_unique_tools(
                        old_tools[name],
                        new_tools[name],
                    ),
                )
            )

    duplicate_added = sorted(set(new.duplicate_tool_names) - set(old.duplicate_tool_names))
    duplicate_resolved = sorted(set(old.duplicate_tool_names) - set(new.duplicate_tool_names))
    changed = bool(added or removed or modified or duplicate_added or duplicate_resolved)

    return RevisionDelta(
        from_revision_id=old.revision_id,
        to_revision_id=new.revision_id,
        added_tools=added,
        removed_tools=removed,
        modified_tools=modified,
        unchanged_tools=unchanged,
        duplicate_names_added=duplicate_added,
        duplicate_names_resolved=duplicate_resolved,
        changed=changed,
    )


def compare_to_trusted(
    revision: DiscoveryRevision,
    trusted_snapshots: list[ToolSnapshot],
) -> TrustedSurfaceStatus:
    """Compare the current complete surface to the currently approved tool baselines."""

    current = _hashes_by_name(revision)
    current_tools = _tools_by_name(revision)
    trusted: dict[str, list[ToolSnapshot]] = {}
    for snapshot in trusted_snapshots:
        trusted.setdefault(snapshot.tool_name, []).append(snapshot)

    trusted_hashes = {
        name: sorted(snapshot.sha256 for snapshot in snapshots)
        for name, snapshots in trusted.items()
    }
    current_names = set(current)
    trusted_names = set(trusted_hashes)
    untrusted = sorted(current_names - trusted_names)
    missing = sorted(trusted_names - current_names)
    unchanged: list[str] = []
    modified: list[ToolRevisionChange] = []

    for name in sorted(current_names & trusted_names):
        if current[name] == trusted_hashes[name]:
            unchanged.append(name)
            continue

        field_changes: list[JsonFieldChange] = []
        if len(current_tools[name]) == 1 and len(trusted[name]) == 1:
            field_changes = _diff_json(
                trusted[name][0].canonical_tool,
                current_tools[name][0].canonical_tool,
            )

        modified.append(
            ToolRevisionChange(
                tool_name=name,
                old_sha256=trusted_hashes[name],
                new_sha256=current[name],
                field_changes=field_changes,
            )
        )

    return TrustedSurfaceStatus(
        revision_id=revision.revision_id,
        untrusted_tools=untrusted,
        missing_trusted_tools=missing,
        modified_from_trusted=modified,
        unchanged_trusted_tools=unchanged,
        review_required=bool(
            untrusted
            or missing
            or modified
            or revision.duplicate_tool_names
        ),
    )
