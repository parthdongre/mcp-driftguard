from __future__ import annotations

from typing import Final

from .models import ToolDelta

PAIR_FEATURE_NAMES: Final[tuple[str, ...]] = (
    "unchanged",
    "lexical_change_ratio",
    "changed_field_count",
    "parameters_added",
    "parameters_removed",
    "required_added",
    "required_removed",
    "type_changes",
    "default_changes",
    "enum_changes",
    "sensitive_terms_added",
    "urls_added",
    "cross_tool_references_added",
    "imperative_terms_added",
)


def pair_feature_map(delta: ToolDelta) -> dict[str, float]:
    """Convert one old/new tool pair into a stable, model-ready numeric feature map."""

    structural = delta.structural
    return {
        "unchanged": float(delta.old.sha256 == delta.new.sha256),
        "lexical_change_ratio": float(delta.lexical_change_ratio),
        "changed_field_count": float(len(delta.changed_fields)),
        "parameters_added": float(len(structural.parameters_added)),
        "parameters_removed": float(len(structural.parameters_removed)),
        "required_added": float(len(structural.required_added)),
        "required_removed": float(len(structural.required_removed)),
        "type_changes": float(len(structural.type_changes)),
        "default_changes": float(len(structural.default_changes)),
        "enum_changes": float(len(structural.enum_changes)),
        "sensitive_terms_added": float(len(structural.sensitive_terms_added)),
        "urls_added": float(len(structural.urls_added)),
        "cross_tool_references_added": float(len(structural.cross_tool_references_added)),
        "imperative_terms_added": float(len(structural.imperative_terms_added)),
    }


def pair_feature_vector(delta: ToolDelta) -> list[float]:
    feature_map = pair_feature_map(delta)
    return [feature_map[name] for name in PAIR_FEATURE_NAMES]
