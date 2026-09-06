from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Literal

from .dataset import PairDatasetRecord
from .models import ChangeClass
from .poisoning import poisoning_security_features, transition_text


class _BinarySklearnBaseline:
    def __init__(self) -> None:
        self._model = None

    @staticmethod
    def _labels(records: list[PairDatasetRecord]) -> list[bool]:
        return [record.label is ChangeClass.MALICIOUS_DRIFT for record in records]

    def _require_binary_training(self, records: list[PairDatasetRecord]) -> list[bool]:
        if not records:
            raise ValueError("At least one training record is required")
        y = self._labels(records)
        if len(set(y)) < 2:
            raise ValueError("Training requires both malicious and non-malicious records")
        return y

    def _positive_probabilities(self, matrix) -> list[float]:
        if self._model is None:
            raise RuntimeError("Baseline has not been fitted")
        probabilities = self._model.predict_proba(matrix)
        classes = list(self._model.classes_)
        positive_index = classes.index(True)
        return [float(row[positive_index]) for row in probabilities]


class SnapshotPoisoningBaseline(_BinarySklearnBaseline):
    """Single-snapshot maliciousness baseline using only the current tool definition.

    This deliberately throws away the trusted old definition. It measures whether the
    temporal pair formulation itself contributes beyond ordinary static text screening.
    """

    def __init__(self) -> None:
        super().__init__()
        self._word = None
        self._char = None

    @staticmethod
    def _texts(records: list[PairDatasetRecord]) -> list[str]:
        return [json.dumps(record.new_tool, sort_keys=True, ensure_ascii=False) for record in records]

    def fit(self, records: Iterable[PairDatasetRecord]) -> SnapshotPoisoningBaseline:
        from scipy.sparse import hstack
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression

        records = list(records)
        y = self._require_binary_training(records)
        texts = self._texts(records)
        self._word = TfidfVectorizer(ngram_range=(1, 2), max_features=35000, sublinear_tf=True)
        self._char = TfidfVectorizer(
            analyzer="char_wb", ngram_range=(3, 5), max_features=50000, sublinear_tf=True
        )
        matrix = hstack(
            [self._word.fit_transform(texts), self._char.fit_transform(texts)], format="csr"
        )
        self._model = LogisticRegression(
            C=4.0, max_iter=4000, class_weight="balanced", random_state=42
        )
        self._model.fit(matrix, y)
        return self

    def predict_proba(self, records: Iterable[PairDatasetRecord]) -> list[float]:
        from scipy.sparse import hstack

        records = list(records)
        if not records:
            return []
        if self._word is None or self._char is None:
            raise RuntimeError("Baseline has not been fitted")
        texts = self._texts(records)
        matrix = hstack([self._word.transform(texts), self._char.transform(texts)], format="csr")
        return self._positive_probabilities(matrix)


class PairAblationBaseline(_BinarySklearnBaseline):
    """Pairwise baseline restricted to text-only or numeric-security-only evidence."""

    def __init__(self, mode: Literal["text_only", "numeric_only"]) -> None:
        super().__init__()
        self.mode = mode
        self._word = None
        self._char = None
        self._numeric = None

    def fit(self, records: Iterable[PairDatasetRecord]) -> PairAblationBaseline:
        from scipy.sparse import hstack
        from sklearn.feature_extraction import DictVectorizer
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression

        records = list(records)
        y = self._require_binary_training(records)
        if self.mode == "text_only":
            texts = [transition_text(record) for record in records]
            self._word = TfidfVectorizer(
                ngram_range=(1, 2), max_features=35000, sublinear_tf=True
            )
            self._char = TfidfVectorizer(
                analyzer="char_wb", ngram_range=(3, 5), max_features=50000, sublinear_tf=True
            )
            matrix = hstack(
                [self._word.fit_transform(texts), self._char.fit_transform(texts)], format="csr"
            )
        else:
            self._numeric = DictVectorizer(sparse=True)
            matrix = self._numeric.fit_transform(
                [poisoning_security_features(record) for record in records]
            )

        self._model = LogisticRegression(
            C=4.0, max_iter=4000, class_weight="balanced", random_state=42
        )
        self._model.fit(matrix, y)
        return self

    def predict_proba(self, records: Iterable[PairDatasetRecord]) -> list[float]:
        from scipy.sparse import hstack

        records = list(records)
        if not records:
            return []
        if self.mode == "text_only":
            if self._word is None or self._char is None:
                raise RuntimeError("Baseline has not been fitted")
            texts = [transition_text(record) for record in records]
            matrix = hstack(
                [self._word.transform(texts), self._char.transform(texts)], format="csr"
            )
        else:
            if self._numeric is None:
                raise RuntimeError("Baseline has not been fitted")
            matrix = self._numeric.transform(
                [poisoning_security_features(record) for record in records]
            )
        return self._positive_probabilities(matrix)
