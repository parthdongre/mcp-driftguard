from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any

from .models import ToolSnapshot

_WHITESPACE = re.compile(r"\s+")


def _normalize_text(value: str) -> str:
    """Collapse insignificant whitespace without rewriting semantic content."""

    return _WHITESPACE.sub(" ", value).strip()


def _canonicalize(value: Any) -> Any:
    """Recursively create a deterministic representation of JSON-compatible data."""

    if isinstance(value, dict):
        return {key: _canonicalize(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        # Array order can be semantically relevant in JSON Schema, so preserve it.
        return [_canonicalize(item) for item in value]
    if isinstance(value, str):
        return _normalize_text(value)
    return value


def canonicalize_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """Return a canonical copy while retaining security-relevant fields and values."""

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
