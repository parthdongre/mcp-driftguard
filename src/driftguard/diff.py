from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any

from .canonicalize import exact_json, validate_snapshot_integrity
from .models import StructuralDelta, ToolDelta, ToolSnapshot

SENSITIVE_TERMS = {
    "credential",
    "credentials",
    "token",
    "api_token",
    "api key",
    "api_key",
    "password",
    "secret",
    "shell",
    "execute",
    "command",
    "delete",
    "upload",
    "send",
    "network",
    "repository",
    "database",
    "payment",
    "ssh",
    "filesystem",
}

IMPERATIVE_TERMS = {
    "always",
    "must",
    "ignore",
    "override",
    "instead",
    "first",
    "before",
    "never",
    "silently",
    "do not tell",
    "do not reveal",
}

_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_TOOL_REF_RE = re.compile(r"(?:tool|function)\s+[`'\"]?([A-Za-z0-9_.:-]+)", re.IGNORECASE)
_TOOL_REF_STOPWORDS = {
    "a",
    "an",
    "automatically",
    "can",
    "executes",
    "for",
    "is",
    "object",
    "that",
    "the",
    "this",
    "to",
    "used",
    "which",
    "will",
    "with",
}


def _input_schema(tool: dict[str, Any]) -> dict[str, Any]:
    schema = tool.get("inputSchema", tool.get("input_schema", {}))
    if not isinstance(schema, dict):
        raise TypeError("A tool input schema must be a JSON object")
    return schema


def _flatten_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        # Keys carry parameter names (e.g. an undocumented optional ``api_key``).
        return " ".join(f"{k} {_flatten_text(v)}" for k, v in value.items())
    if isinstance(value, list):
        return " ".join(_flatten_text(v) for v in value)
    return ""


def _iter_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _iter_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_strings(child)


def _new_terms(old_text: str, new_text: str, vocabulary: set[str]) -> list[str]:
    old_lower = old_text.lower()
    new_lower = new_text.lower()
    return sorted(term for term in vocabulary if term in new_lower and term not in old_lower)


def _new_urls(old_text: str, new_text: str) -> list[str]:
    return sorted(set(_URL_RE.findall(new_text)) - set(_URL_RE.findall(old_text)))


def _tool_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    for text in _iter_strings(value):
        for match in _TOOL_REF_RE.findall(text):
            candidate = match.lower().rstrip(".,;:!?")
            if candidate and candidate not in _TOOL_REF_STOPWORDS:
                refs.add(candidate)
    return refs


def _new_tool_refs(old_value: Any, new_value: Any) -> list[str]:
    return sorted(_tool_refs(new_value) - _tool_refs(old_value))


def _schema_properties(schema: dict[str, Any]) -> dict[str, Any]:
    props = schema.get("properties", {})
    return props if isinstance(props, dict) else {}


def _schema_required(schema: dict[str, Any]) -> set[str]:
    required = schema.get("required", [])
    return {str(item) for item in required} if isinstance(required, list) else set()


def _compare_leaf(
    path: str,
    old_param: dict[str, Any],
    new_param: dict[str, Any],
    type_changes: dict[str, tuple[Any, Any]],
    default_changes: dict[str, tuple[Any, Any]],
    enum_changes: list[str],
) -> None:
    old_type = old_param.get("type")
    new_type = new_param.get("type")
    if old_type != new_type:
        type_changes[path] = (old_type, new_type)

    old_default = old_param.get("default")
    new_default = new_param.get("default")
    if ("default" in old_param) != ("default" in new_param) or exact_json(
        old_default
    ) != exact_json(new_default):
        default_changes[path] = (old_default, new_default)

    if ("enum" in old_param) != ("enum" in new_param) or exact_json(
        old_param.get("enum")
    ) != exact_json(new_param.get("enum")):
        enum_changes.append(path)


def structural_delta(old: ToolSnapshot, new: ToolSnapshot) -> StructuralDelta:
    """Diff parameters, including nested object properties and array ``items``.

    Top-level parameters keep their bare names. Nested parameters use dotted paths
    (``options.command``) and array element schemas use ``[]`` (``tags[]``). Children
    are only diffed beneath parameters present in both versions, so adding a new object
    parameter counts once rather than once per nested field.
    """

    old_tool = old.canonical_tool
    new_tool = new.canonical_tool

    parameters_added: list[str] = []
    parameters_removed: list[str] = []
    required_added: list[str] = []
    required_removed: list[str] = []
    type_changes: dict[str, tuple[Any, Any]] = {}
    default_changes: dict[str, tuple[Any, Any]] = {}
    enum_changes: list[str] = []

    # Iterative walk: no recursion limit on deeply nested schemas.
    stack: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
        ("", _input_schema(old_tool), _input_schema(new_tool))
    ]
    while stack:
        prefix, old_schema, new_schema = stack.pop()
        old_props = _schema_properties(old_schema)
        new_props = _schema_properties(new_schema)
        old_names = set(old_props)
        new_names = set(new_props)
        parameters_added.extend(prefix + name for name in new_names - old_names)
        parameters_removed.extend(prefix + name for name in old_names - new_names)
        old_required = _schema_required(old_schema)
        new_required = _schema_required(new_schema)
        required_added.extend(prefix + name for name in new_required - old_required)
        required_removed.extend(prefix + name for name in old_required - new_required)

        for name in old_names & new_names:
            old_param = old_props[name]
            new_param = new_props[name]
            if not isinstance(old_param, dict) or not isinstance(new_param, dict):
                continue
            path = prefix + name
            _compare_leaf(
                path, old_param, new_param, type_changes, default_changes, enum_changes
            )
            stack.append((path + ".", old_param, new_param))
            old_items = old_param.get("items")
            new_items = new_param.get("items")
            if isinstance(old_items, dict) and isinstance(new_items, dict):
                _compare_leaf(
                    path + "[]",
                    old_items,
                    new_items,
                    type_changes,
                    default_changes,
                    enum_changes,
                )
                stack.append((path + "[].", old_items, new_items))

    old_text = _flatten_text(old_tool)
    new_text = _flatten_text(new_tool)

    return StructuralDelta(
        parameters_added=sorted(parameters_added),
        parameters_removed=sorted(parameters_removed),
        required_added=sorted(required_added),
        required_removed=sorted(required_removed),
        type_changes=dict(sorted(type_changes.items())),
        default_changes=dict(sorted(default_changes.items())),
        enum_changes=sorted(enum_changes),
        sensitive_terms_added=_new_terms(old_text, new_text, SENSITIVE_TERMS),
        urls_added=_new_urls(old_text, new_text),
        cross_tool_references_added=_new_tool_refs(old_tool, new_tool),
        imperative_terms_added=_new_terms(old_text, new_text, IMPERATIVE_TERMS),
    )


def build_delta(old: ToolSnapshot, new: ToolSnapshot) -> ToolDelta:
    validate_snapshot_integrity(old)
    validate_snapshot_integrity(new)
    old_tool = old.canonical_tool
    new_tool = new.canonical_tool
    changed_fields = sorted(
        key
        for key in set(old_tool) | set(new_tool)
        if (key in old_tool) != (key in new_tool)
        or exact_json(old_tool.get(key)) != exact_json(new_tool.get(key))
    )

    old_serialized = json.dumps(old_tool, sort_keys=True, ensure_ascii=False)
    new_serialized = json.dumps(new_tool, sort_keys=True, ensure_ascii=False)
    similarity = SequenceMatcher(None, old_serialized, new_serialized).ratio()

    return ToolDelta(
        old=old,
        new=new,
        structural=structural_delta(old, new),
        changed_fields=changed_fields,
        lexical_change_ratio=1.0 - similarity,
    )
