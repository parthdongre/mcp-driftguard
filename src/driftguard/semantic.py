from __future__ import annotations

import json
import math
from collections.abc import Sequence
from typing import Protocol

from .features import PAIR_FEATURE_NAMES, pair_feature_vector
from .ml import PairwiseLogisticDetector
from .models import ToolDelta

SEMANTIC_FEATURE_NAMES = (
    "description_semantic_distance",
    "schema_semantic_distance",
    "parameter_semantic_distance",
    "full_semantic_distance",
)
HYBRID_FEATURE_NAMES = PAIR_FEATURE_NAMES + SEMANTIC_FEATURE_NAMES


class TextEmbedder(Protocol):
    """Small provider-neutral embedding boundary used by semantic drift features."""

    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


class SentenceTransformerEmbedder:
    """Optional sentence-transformers adapter; no model dependency leaks into core."""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                'Semantic support is optional. Install with: pip install -e ".[semantic]"'
            ) from exc
        self.model_name = model_name
        self._model = SentenceTransformer(model_name)

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        embeddings = self._model.encode(list(texts), normalize_embeddings=True)
        return [[float(value) for value in row] for row in embeddings]


def _cosine_distance(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("Embedding dimensions must match")
    if list(left) == list(right):
        return 0.0
    if not left:
        return 0.0

    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))

    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0 if list(left) == list(right) else 1.0

    similarity = max(-1.0, min(1.0, dot / (left_norm * right_norm)))
    return (1.0 - similarity) / 2.0


def _description(tool: dict) -> str:
    value = tool.get("description", "")
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True)


def _schema_text(tool: dict) -> str:
    schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    return json.dumps(schema, sort_keys=True, ensure_ascii=False)


def _parameter_text(tool: dict) -> str:
    schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    if not isinstance(properties, dict):
        return ""

    parts: list[str] = []
    for name in sorted(properties):
        definition = properties[name]
        if isinstance(definition, dict):
            description = definition.get("description", "")
            parts.append(f"{name}: {description}")
        else:
            parts.append(str(name))
    return "\n".join(parts)


def _full_text(tool: dict) -> str:
    return json.dumps(tool, sort_keys=True, ensure_ascii=False)


def semantic_feature_map(delta: ToolDelta, embedder: TextEmbedder) -> dict[str, float]:
    old_tool = delta.old.canonical_tool
    new_tool = delta.new.canonical_tool

    texts = [
        _description(old_tool),
        _description(new_tool),
        _schema_text(old_tool),
        _schema_text(new_tool),
        _parameter_text(old_tool),
        _parameter_text(new_tool),
        _full_text(old_tool),
        _full_text(new_tool),
    ]
    embeddings = list(embedder.encode(texts))
    if len(embeddings) != len(texts):
        raise ValueError("Embedder must return one vector per input text")

    return {
        "description_semantic_distance": _cosine_distance(embeddings[0], embeddings[1]),
        "schema_semantic_distance": _cosine_distance(embeddings[2], embeddings[3]),
        "parameter_semantic_distance": _cosine_distance(embeddings[4], embeddings[5]),
        "full_semantic_distance": _cosine_distance(embeddings[6], embeddings[7]),
    }


def hybrid_feature_vector(delta: ToolDelta, embedder: TextEmbedder) -> list[float]:
    semantic = semantic_feature_map(delta, embedder)
    return pair_feature_vector(delta) + [semantic[name] for name in SEMANTIC_FEATURE_NAMES]


class HybridSemanticLogisticDetector(PairwiseLogisticDetector):
    """Pairwise logistic baseline augmented with provider-neutral embedding distances."""

    def __init__(
        self,
        embedder: TextEmbedder,
        *,
        confidence_threshold: float = 0.55,
        margin_threshold: float = 0.10,
    ) -> None:
        self.embedder = embedder
        super().__init__(
            confidence_threshold=confidence_threshold,
            margin_threshold=margin_threshold,
            feature_extractor=lambda delta: hybrid_feature_vector(delta, self.embedder),
            feature_names=HYBRID_FEATURE_NAMES,
        )
