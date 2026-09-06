from __future__ import annotations

import re
from typing import Any

from .dataset import PairDatasetRecord
from .models import PairFeatures

_EXTERNAL_URL_RE = re.compile(r"https?://", re.IGNORECASE)
_EXTERNAL_PARAMETER_TERMS = (
    "url",
    "uri",
    "callback",
    "webhook",
    "endpoint",
    "destination",
    "redirect",
    "sink",
    "target",
)
_AUTOMATIC_TERMS = (
    "automatic",
    "automatically",
    "without confirmation",
    "without asking",
    "by default",
)


def _input_schema(tool: dict[str, Any]) -> dict[str, Any]:
    schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    return schema if isinstance(schema, dict) else {}


def _properties(tool: dict[str, Any]) -> dict[str, Any]:
    properties = _input_schema(tool).get("properties", {})
    return properties if isinstance(properties, dict) else {}


def _annotations(tool: dict[str, Any]) -> dict[str, Any]:
    annotations = tool.get("annotations", {})
    return annotations if isinstance(annotations, dict) else {}


def _contains_external_url(value: Any) -> bool:
    if isinstance(value, str):
        return _EXTERNAL_URL_RE.search(value) is not None
    if isinstance(value, dict):
        return any(_contains_external_url(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_external_url(child) for child in value)
    return False


def _flatten_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(f"{key} {_flatten_text(child)}" for key, child in value.items())
    if isinstance(value, list):
        return " ".join(_flatten_text(child) for child in value)
    return str(value) if value is not None else ""


def _new_external_defaults(old_tool: dict[str, Any], new_tool: dict[str, Any]) -> tuple[int, int]:
    old_properties = _properties(old_tool)
    new_properties = _properties(new_tool)
    external_defaults = 0
    external_named_parameters = 0

    for name, new_schema in new_properties.items():
        if not isinstance(new_schema, dict):
            continue
        old_schema = old_properties.get(name, {})
        if not isinstance(old_schema, dict):
            old_schema = {}
        old_default = old_schema.get("default")
        new_default = new_schema.get("default")
        if new_default != old_default and _contains_external_url(new_default):
            external_defaults += 1
        if name not in old_properties and any(term in name.lower() for term in _EXTERNAL_PARAMETER_TERMS):
            external_named_parameters += 1

    return external_defaults, external_named_parameters


def structural_poisoning_features(
    record: PairDatasetRecord,
    pair_features: PairFeatures,
) -> dict[str, float]:
    """Return generic invariants for structural-only MCP poisoning.

    These features intentionally describe security relationships rather than attack-family
    names. They target two broad classes of post-approval manipulation:

    1. introducing attacker-controlled external destinations through defaults or new sink
       parameters; and
    2. making the effective capability contradict safety annotations such as readOnlyHint.

    They are suitable for hard-negative training because a user-supplied URL parameter with
    no external default, or a mutating tool whose annotations correctly declare mutation,
    does not trigger the contradiction features.
    """

    external_defaults, external_named_parameters = _new_external_defaults(
        record.old_tool,
        record.new_tool,
    )
    new_annotations = _annotations(record.new_tool)
    old_annotations = _annotations(record.old_tool)
    capability_delta = pair_features.capability_delta

    mutating_added = bool(
        {"write", "delete", "execute"} & set(capability_delta.operations_added)
        or {"mutate", "destroy", "execute"} & set(capability_delta.effects_added)
    )
    destructive_added = bool(
        "delete" in capability_delta.operations_added
        or "destroy" in capability_delta.effects_added
    )
    readonly_claim = new_annotations.get("readOnlyHint") is True
    destructive_safe_claim = new_annotations.get("destructiveHint") is False
    annotations_unchanged = new_annotations == old_annotations

    new_text = _flatten_text(record.new_tool).lower()
    old_text = _flatten_text(record.old_tool).lower()
    automatic_added = any(term in new_text and term not in old_text for term in _AUTOMATIC_TERMS)

    return {
        "security__external_default_added": float(external_defaults),
        "security__external_destination_parameter_added": float(external_named_parameters),
        "security__readonly_capability_contradiction": float(readonly_claim and mutating_added),
        "security__destructive_annotation_contradiction": float(
            destructive_safe_claim and destructive_added
        ),
        "security__stale_safety_annotation_on_mutation": float(
            annotations_unchanged and readonly_claim and mutating_added
        ),
        "interaction__external_default_x_new_destination_param": float(
            external_defaults > 0 and external_named_parameters > 0
        ),
        "interaction__external_default_x_automatic": float(
            external_defaults > 0 and automatic_added
        ),
        "interaction__readonly_x_destructive": float(readonly_claim and destructive_added),
    }
