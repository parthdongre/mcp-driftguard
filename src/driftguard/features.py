from __future__ import annotations

from difflib import SequenceMatcher

from .capabilities import capability_delta, capability_escalation_score, extract_capability_profile
from .embeddings import EmbeddingCache, EmbeddingProvider, view_embedding_drift
from .models import PairFeatures, SemanticViews, ToolDelta
from .views import extract_semantic_views


def _drift(old: str, new: str) -> float:
    if not old and not new:
        return 0.0
    return 1.0 - SequenceMatcher(None, old, new).ratio()


def _view_drift(old: SemanticViews, new: SemanticViews) -> dict[str, float]:
    return {
        "purpose": _drift(old.purpose, new.purpose),
        "input_contract": _drift(old.input_contract, new.input_contract),
        "output_contract": _drift(old.output_contract, new.output_contract),
        "capability_safety": _drift(old.capability_safety, new.capability_safety),
        "full_schema": _drift(old.full_schema, new.full_schema),
    }


def extract_pair_features(
    delta: ToolDelta,
    embedding_provider: EmbeddingProvider | None = None,
    embedding_cache: EmbeddingCache | None = None,
) -> PairFeatures:
    """Build the hybrid old/new feature vector used by research baselines and models."""

    old_views = extract_semantic_views(delta.old)
    new_views = extract_semantic_views(delta.new)
    old_capability = extract_capability_profile(delta.old)
    new_capability = extract_capability_profile(delta.new)
    cap_delta = capability_delta(old_capability, new_capability)
    s = delta.structural

    sensitive_terms_added = float(len(s.sensitive_terms_added))
    urls_added = float(len(s.urls_added))
    cross_tool_references_added = float(len(s.cross_tool_references_added))
    imperative_terms_added = float(len(s.imperative_terms_added))
    security_event_count = (
        sensitive_terms_added
        + urls_added
        + cross_tool_references_added
        + imperative_terms_added
    )

    structural_counts = {
        "parameters_added": float(len(s.parameters_added)),
        "parameters_removed": float(len(s.parameters_removed)),
        "required_added": float(len(s.required_added)),
        "required_removed": float(len(s.required_removed)),
        "type_changes": float(len(s.type_changes)),
        "default_changes": float(len(s.default_changes)),
        "enum_changes": float(len(s.enum_changes)),
        "sensitive_terms_added": sensitive_terms_added,
        "urls_added": urls_added,
        "cross_tool_references_added": cross_tool_references_added,
        "imperative_terms_added": imperative_terms_added,
        "security_event_count": security_event_count,
    }

    semantic_drift = (
        view_embedding_drift(old_views, new_views, embedding_provider, embedding_cache)
        if embedding_provider is not None
        else {}
    )

    return PairFeatures(
        view_lexical_drift={
            key: round(value, 6) for key, value in _view_drift(old_views, new_views).items()
        },
        view_semantic_drift=semantic_drift,
        structural_counts=structural_counts,
        capability_delta=cap_delta,
        capability_escalation_score=capability_escalation_score(cap_delta),
        lexical_change_ratio=round(delta.lexical_change_ratio, 6),
    )


def flatten_numeric_features(features: PairFeatures) -> dict[str, float]:
    """Flatten named features into stable scalar columns for sklearn/XGBoost."""

    result = {
        f"view_drift__{key}": value for key, value in features.view_lexical_drift.items()
    }
    result.update(
        {
            f"semantic_drift__{key}": value
            for key, value in features.view_semantic_drift.items()
        }
    )
    result.update(
        {f"struct__{key}": value for key, value in features.structural_counts.items()}
    )
    result["capability_escalation_score"] = features.capability_escalation_score
    result["lexical_change_ratio"] = features.lexical_change_ratio
    return result
