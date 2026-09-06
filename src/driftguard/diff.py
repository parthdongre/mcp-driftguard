from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any

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
    return tool.get("inputSchema") or tool.get("input_schema") or {}


def _properties(tool: dict[str, Any]) -> dict[str, Any]:
    schema = _input_schema(tool)
    props = schema.get("properties", {})
    return props if isinstance(props, dict) else {}


def _required(tool: dict[str, Any]) -> set[str]:
    required = _input_schema(tool).get("required", [])
    return {str(item) for item in required} if isinstance(required, list) else set()


def _flatten_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten_text(v) for v in value.values())
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
            candidate = match.lower()
            if candidate not in _TOOL_REF_STOPWORDS:
                refs.add(candidate)
    return refs


def _new_tool_refs(old_value: Any, new_value: Any) -> list[str]:
    return sorted(_tool_refs(new_value) - _tool_refs(old_value))


def structural_delta(old: ToolSnapshot, new: ToolSnapshot) -> StructuralDelta:
    old_tool = old.canonical_tool
    new_tool = new.canonical_tool

    old_props = _properties(old_tool)
    new_props = _properties(new_tool)

    old_names = set(old_props)
    new_names = set(new_props)

    type_changes: dict[str, tuple[str | None, str | None]] = {}
    default_changes: dict[str, tuple[Any, Any]] = {}
    enum_changes: list[str] = []

    for name in sorted(old_names & new_names):
        old_param = old_props.get(name, {})
        new_param = new_props.get(name, {})
        if not isinstance(old_param, dict) or not isinstance(new_param, dict):
            continue

        old_type = old_param.get("type")
        new_type = new_param.get("type")
        if old_type != new_type:
            type_changes[name] = (old_type, new_type)

        old_default = old_param.get("default")
        new_default = new_param.get("default")
        if old_default != new_default:
            default_changes[name] = (old_default, new_default)

        if old_param.get("enum") != new_param.get("enum"):
            enum_changes.append(name)

    old_text = _flatten_text(old_tool)
    new_text = _flatten_text(new_tool)

    return StructuralDelta(
        parameters_added=sorted(new_names - old_names),
        parameters_removed=sorted(old_names - new_names),
        required_added=sorted(_required(new_tool) - _required(old_tool)),
        required_removed=sorted(_required(old_tool) - _required(new_tool)),
        type_changes=type_changes,
        default_changes=default_changes,
        enum_changes=enum_changes,
        sensitive_terms_added=_new_terms(old_text, new_text, SENSITIVE_TERMS),
        urls_added=_new_urls(old_text, new_text),
        cross_tool_references_added=_new_tool_refs(old_tool, new_tool),
        imperative_terms_added=_new_terms(old_text, new_text, IMPERATIVE_TERMS),
    )


def build_delta(old: ToolSnapshot, new: ToolSnapshot) -> ToolDelta:
    old_tool = old.canonical_tool
    new_tool = new.canonical_tool
    changed_fields = sorted(
        key for key in set(old_tool) | set(new_tool) if old_tool.get(key) != new_tool.get(key)
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
