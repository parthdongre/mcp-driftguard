from __future__ import annotations

from collections.abc import Iterable

from .dataset import PairDatasetRecord
from .embeddings import EmbeddingCache, EmbeddingProvider
from .learning import record_features


class XGBoostPairClassifier:
    """Gradient-boosted tree baseline over the same named pair features as logistic."""

    def __init__(
        self,
        *,
        n_estimators: int = 100,
        max_depth: int = 3,
        learning_rate: float = 0.08,
    ) -> None:
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self._vectorizer = None
        self._encoder = None
        self._model = None
        self._embedding_provider: EmbeddingProvider | None = None
        self._embedding_cache: EmbeddingCache | None = None

    def fit(
        self,
        records: Iterable[PairDatasetRecord],
        *,
        embedding_provider: EmbeddingProvider | None = None,
        embedding_cache: EmbeddingCache | None = None,
    ) -> XGBoostPairClassifier:
        try:
            from sklearn.feature_extraction import DictVectorizer
            from sklearn.preprocessing import LabelEncoder
            from sklearn.utils.class_weight import compute_sample_weight
            from xgboost import XGBClassifier
        except ImportError as exc:
            raise RuntimeError(
                "xgboost and scikit-learn are required for the gradient-boosted baseline"
            ) from exc

        records = list(records)
        if not records:
            raise ValueError("At least one training record is required")
        labels = {record.label.value for record in records}
        if len(labels) < 2:
            raise ValueError("Training requires at least two change classes")

        self._embedding_provider = embedding_provider
        self._embedding_cache = embedding_cache or EmbeddingCache()
        rows = [
            record_features(record, embedding_provider, self._embedding_cache)
            for record in records
        ]
        y_labels = [record.label.value for record in records]

        self._vectorizer = DictVectorizer(sparse=False)
        x = self._vectorizer.fit_transform(rows)
        self._encoder = LabelEncoder()
        y = self._encoder.fit_transform(y_labels)
        weights = compute_sample_weight(class_weight="balanced", y=y)

        self._model = XGBClassifier(
            objective="multi:softprob",
            num_class=len(self._encoder.classes_),
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            learning_rate=self.learning_rate,
            subsample=0.9,
            colsample_bytree=0.9,
            reg_lambda=1.0,
            eval_metric="mlogloss",
            random_state=42,
            n_jobs=2,
            tree_method="hist",
        )
        self._model.fit(x, y, sample_weight=weights)
        return self

    def _check_fitted(self) -> None:
        if self._vectorizer is None or self._encoder is None or self._model is None:
            raise RuntimeError("Classifier has not been fitted")

    def predict_proba(self, record: PairDatasetRecord) -> dict[str, float]:
        self._check_fitted()
        row = record_features(record, self._embedding_provider, self._embedding_cache)
        x = self._vectorizer.transform([row])
        probabilities = self._model.predict_proba(x)[0]
        return {
            str(label): float(probability)
            for label, probability in zip(
                self._encoder.classes_,
                probabilities,
                strict=True,
            )
        }
