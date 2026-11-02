from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from typing import Any

from .models import ToolSnapshot

_WHITESPACE = re.compile(r"\s+")
_TEXT_FIELDS = {"description", "title"}
_SCHEMA_MAP_FIELDS = {"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"}
_SCHEMA_FIELDS = {
    "additionalProperties",
    "additionalItems",
    "items",
    "contains",
    "not",
    "if",
    "then",
    "else",
    "propertyNames",
    "unevaluatedProperties",
    "unevaluatedItems",
    "contentSchema",
}
_SCHEMA_ARRAY_FIELDS = {"allOf", "anyOf", "oneOf", "prefixItems"}


def _normalize_text(value: str) -> str:
    """Collapse presentation-only whitespace in human-facing schema text."""

    return _WHITESPACE.sub(" ", value).strip()


def _stable_sort_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _validate_json(value: Any) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    if isinstance(value, list):
        for item in value:
            _validate_json(item)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _validate_json(item)
        return
    raise ValueError("Tool definitions must contain only finite JSON values and string keys")


def exact_json(value: Any) -> str:
    """Stable JSON without semantic normalization, suitable for exact consent binding."""

    _validate_json(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def exact_hash(value: Any) -> str:
    return hashlib.sha256(exact_json(value).encode("utf-8")).hexdigest()


def _canonical_schema(value: Any) -> Any:
    if not isinstance(value, dict):
        return deepcopy(value)
    result = {}
    for key, child in sorted(value.items()):
        if key in _TEXT_FIELDS and isinstance(child, str):
            result[key] = _normalize_text(child)
        elif key in _SCHEMA_MAP_FIELDS and isinstance(child, dict):
            result[key] = {
                name: _canonical_schema(schema) for name, schema in sorted(child.items())
            }
        elif key in _SCHEMA_FIELDS:
            result[key] = (
                [_canonical_schema(item) for item in child]
                if isinstance(child, list)
                else _canonical_schema(child)
            )
        elif key in _SCHEMA_ARRAY_FIELDS and isinstance(child, list):
            result[key] = [_canonical_schema(item) for item in child]
        elif key == "dependencies" and isinstance(child, dict):
            result[key] = {
                name: (_canonical_schema(item) if isinstance(item, dict) else deepcopy(item))
                for name, item in sorted(child.items())
            }
        elif key in {"required", "enum"} and isinstance(child, list):
            # Members are data, including objects with keys named description/enum.
            result[key] = sorted(deepcopy(child), key=_stable_sort_key)
        else:
            # Defaults, consts, examples and unknown extension keywords contain data.
            result[key] = deepcopy(child)
    return result


def canonicalize_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """Return a canonical copy while retaining security-relevant literal values."""

    if not isinstance(tool, dict):
        raise TypeError("A tool definition must be a JSON object")
    _validate_json(tool)
    result = {}
    for key, value in sorted(tool.items()):
        if key in _TEXT_FIELDS and isinstance(value, str):
            result[key] = _normalize_text(value)
        elif key in {"inputSchema", "input_schema", "outputSchema", "output_schema"}:
            result[key] = _canonical_schema(value)
        else:
            result[key] = deepcopy(value)
    return result


def canonical_json(tool: dict[str, Any]) -> str:
    canonical = canonicalize_tool(tool)
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def schema_hash(tool: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(tool).encode("utf-8")).hexdigest()


def validate_snapshot_integrity(snapshot: ToolSnapshot) -> None:
    """Reject externally constructed or subsequently mutated snapshot identities."""

    if (
        snapshot.sha256 != schema_hash(snapshot.canonical_tool)
        or exact_json(snapshot.canonical_tool) != exact_json(canonicalize_tool(snapshot.raw_tool))
        or snapshot.tool_name != str(snapshot.canonical_tool.get("name", "unknown-tool"))
    ):
        raise ValueError("Tool snapshot content does not match its recorded identity")


def make_snapshot(
    *,
    server_id: str,
    tool: dict[str, Any],
    protocol_version: str | None = None,
    approval_state: str = "unreviewed",
    parent_snapshot_id: str | None = None,
) -> ToolSnapshot:
    """Detach an observed definition and record its canonical integrity identity.

    Nested JSON containers remain ordinary dictionaries/lists; consumers verify the
    recorded identity before comparing snapshots rather than trusting mutable contents.
    """

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
