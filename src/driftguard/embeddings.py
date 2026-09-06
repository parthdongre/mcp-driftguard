from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from .models import SemanticViews


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Minimal provider contract used by the field-aware semantic pipeline."""

    @property
    def model_id(self) -> str: ...

    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


class EmbeddingCache:
    """Small in-memory cache keyed by provider identity and exact view text."""

    def __init__(self) -> None:
        self._vectors: dict[tuple[str, str], list[float]] = {}

    @staticmethod
    def _text_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def get_or_encode(
        self,
        provider: EmbeddingProvider,
        texts: Sequence[str],
    ) -> list[list[float]]:
        vectors: list[list[float] | None] = [None] * len(texts)
        missing_indices: list[int] = []
        missing_texts: list[str] = []

        for index, text in enumerate(texts):
            key = (provider.model_id, self._text_hash(text))
            cached = self._vectors.get(key)
            if cached is None:
                missing_indices.append(index)
                missing_texts.append(text)
            else:
                vectors[index] = cached

        if missing_texts:
            encoded = provider.encode(missing_texts)
            if len(encoded) != len(missing_texts):
                raise ValueError("Embedding provider returned the wrong number of vectors")
            for index, text, vector in zip(missing_indices, missing_texts, encoded, strict=True):
                normalized = [float(value) for value in vector]
                self._vectors[(provider.model_id, self._text_hash(text))] = normalized
                vectors[index] = normalized

        if any(vector is None for vector in vectors):
            raise RuntimeError("Embedding cache failed to resolve every requested vector")
        return [vector for vector in vectors if vector is not None]


class SentenceTransformerProvider:
    """Lazy adapter for sentence-transformers, kept outside the core dependency set."""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        self.model_name = model_name
        self._model = None

    @property
    def model_id(self) -> str:
        return self.model_name

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    "sentence-transformers is required for semantic embeddings; "
                    "install mcp-driftguard[ml]"
                ) from exc
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._load()
        vectors = model.encode(
            list(texts),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [[float(value) for value in vector] for vector in vectors]


def cosine_distance(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("Embedding dimensions do not match")
    if not left:
        return 0.0

    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 and right_norm == 0.0:
        return 0.0
    if left_norm == 0.0 or right_norm == 0.0:
        return 1.0

    similarity = dot / (left_norm * right_norm)
    similarity = min(1.0, max(-1.0, similarity))
    return 1.0 - similarity


def view_embedding_drift(
    old: SemanticViews,
    new: SemanticViews,
    provider: EmbeddingProvider,
    cache: EmbeddingCache | None = None,
) -> dict[str, float]:
    """Compute cosine drift independently for each field-aware schema view."""

    names = ["purpose", "input_contract", "output_contract", "capability_safety", "full_schema"]
    old_texts = [getattr(old, name) for name in names]
    new_texts = [getattr(new, name) for name in names]
    texts = old_texts + new_texts

    vectors = cache.get_or_encode(provider, texts) if cache else provider.encode(texts)
    if len(vectors) != len(texts):
        raise ValueError("Embedding provider returned the wrong number of vectors")

    old_vectors = vectors[: len(names)]
    new_vectors = vectors[len(names) :]
    return {
        name: round(cosine_distance(old_vec, new_vec), 6)
        for name, old_vec, new_vec in zip(names, old_vectors, new_vectors, strict=True)
    }
