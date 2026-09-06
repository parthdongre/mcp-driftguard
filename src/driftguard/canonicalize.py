from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any

from .models import ToolSnapshot

_WHITESPACE = re.compile(r"\s+")
_TEXT_FIELDS = {"description", "title"}
_SET_LIKE_ARRAY_FIELDS = {"required", "enum"}


def _normalize_text(value: str) -> str:
    """Collapse presentation-only whitespace in human-facing schema text."""

    return _WHITESPACE.sub(" ", value).strip()


def _stable_sort_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _canonicalize(value: Any, *, field_name: str | None = None) -> Any:
    """Create a deterministic representation without changing schema semantics.

    Only human-facing ``description`` and ``title`` strings receive whitespace
    normalization. Literal-bearing values such as defaults, regex patterns, enum
    members, examples, paths, and tool names are preserved byte-for-byte because
    whitespace can be meaningful there.

    JSON Schema ``required`` and ``enum`` arrays are set-like for validation, so their
    ordering is normalized after recursively canonicalizing their members. Other arrays
    preserve order because ordering can affect meaning or downstream presentation.
    """

    if isinstance(value, dict):
        return {
            key: _canonicalize(value[key], field_name=key)
            for key in sorted(value)
        }
    if isinstance(value, list):
        items = [_canonicalize(item) for item in value]
        if field_name in _SET_LIKE_ARRAY_FIELDS:
            return sorted(items, key=_stable_sort_key)
        return items
    if isinstance(value, str) and field_name in _TEXT_FIELDS:
        return _normalize_text(value)
    return value


def canonicalize_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """Return a canonical copy while retaining security-relevant literal values."""

    return _canonicalize(deepcopy(tool))


def canonical_json(tool: dict[str, Any]) -> str:
    canonical = canonicalize_tool(tool)
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def schema_hash(tool: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(tool).encode("utf-8")).hexdigest()


def make_snapshot(
    *,
    server_id: str,
    tool: dict[str, Any],
    protocol_version: str | None = None,
    approval_state: str = "unreviewed",
    parent_snapshot_id: str | None = None,
) -> ToolSnapshot:
    """Convert an observed MCP tool definition into an immutable logical snapshot."""

    canonical = canonicalize_tool(tool)
    tool_name = str(canonical.get("name", "unknown-tool"))
    return ToolSnapshot(
        server_id=server_id,
        tool_name=tool_name,
        raw_tool=deepcopy(tool),
        canonical_tool=canonical,
        sha256=schema_hash(canonical),
        protocol_version=protocol_version,
        approval_state=approval_state,
        parent_snapshot_id=parent_snapshot_id,
    )
