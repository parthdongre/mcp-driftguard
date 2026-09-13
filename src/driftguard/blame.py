from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .revisions import DiscoveryRevision, RevisionTool


class FieldBlame(BaseModel):
    """Revision that most recently introduced or changed one current schema field."""

    path: str
    revision_id: str
    observed_at: datetime


class ToolBlame(BaseModel):
    tool_name: str
    target_revision_id: str
    tool_sha256: str | None = None
    ambiguous: bool = False
    ambiguity_reason: str | None = None
    fields: list[FieldBlame] = Field(default_factory=list)


def _pointer_segment(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _child_path(parent: str, key: str) -> str:
    segment = _pointer_segment(key)
    return f"{parent}/{segment}" if parent else f"/{segment}"


def _flatten_fields(value: Any, path: str = "") -> dict[str, Any]:
    """Flatten canonical JSON into stable leaf paths; arrays remain atomic."""

    if isinstance(value, dict):
        if not value:
            return {path or "/": {}}

        flattened: dict[str, Any] = {}
        for key in sorted(value):
            flattened.update(_flatten_fields(value[key], _child_path(path, key)))
        return flattened

    return {path or "/": value}


def _matching_tools(revision: DiscoveryRevision, tool_name: str) -> list[RevisionTool]:
    return [tool for tool in revision.tools if tool.name == tool_name]


def blame_tool(
    revisions: list[DiscoveryRevision],
    *,
    tool_name: str,
    revision_id: str | None = None,
    path_prefix: str | None = None,
) -> ToolBlame | None:
    """Trace current field provenance through a server's chronological revisions.

    Duplicate-name revisions break unambiguous continuity. If a later unique version
    reappears, it begins a fresh provenance chain, similar to a file being removed and
    recreated.
    """

    if not revisions:
        return None

    target_index = len(revisions) - 1
    if revision_id is not None:
        for index, revision in enumerate(revisions):
            if revision.revision_id == revision_id:
                target_index = index
                break
        else:
            return None

    target = revisions[target_index]
    target_matches = _matching_tools(target, tool_name)
    if not target_matches:
        return None
    if len(target_matches) != 1:
        return ToolBlame(
            tool_name=tool_name,
            target_revision_id=target.revision_id,
            ambiguous=True,
            ambiguity_reason="Target revision contains duplicate definitions for this tool name.",
        )

    previous_fields: dict[str, Any] | None = None
    field_blame: dict[str, FieldBlame] = {}

    for revision in revisions[: target_index + 1]:
        matches = _matching_tools(revision, tool_name)

        if len(matches) != 1:
            previous_fields = None
            field_blame = {}
            continue

        current_fields = _flatten_fields(matches[0].canonical_tool)

        if previous_fields is None:
            field_blame = {
                path: FieldBlame(
                    path=path,
                    revision_id=revision.revision_id,
                    observed_at=revision.observed_at,
                )
                for path in current_fields
            }
        else:
            for path, value in current_fields.items():
                if path not in previous_fields or previous_fields[path] != value:
                    field_blame[path] = FieldBlame(
                        path=path,
                        revision_id=revision.revision_id,
                        observed_at=revision.observed_at,
                    )

            for removed_path in set(previous_fields) - set(current_fields):
                field_blame.pop(removed_path, None)

        previous_fields = current_fields

    fields = sorted(field_blame.values(), key=lambda item: item.path)
    if path_prefix:
        normalized = path_prefix.rstrip("/") or "/"
        fields = [
            item
            for item in fields
            if item.path == normalized
            or (
                normalized != "/"
                and item.path.startswith(normalized + "/")
            )
        ]

    return ToolBlame(
        tool_name=tool_name,
        target_revision_id=target.revision_id,
        tool_sha256=target_matches[0].sha256,
        fields=fields,
    )
