from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from random import Random

from .canonicalize import make_snapshot
from .dataset import PairDatasetRecord
from .diff import build_delta
from .embeddings import EmbeddingCache, EmbeddingProvider
from .features import extract_pair_features, flatten_numeric_features
from .models import ChangeClass, RiskAssessment


@dataclass(frozen=True)
class GroupedSplit:
    train: list[PairDatasetRecord]
    validation: list[PairDatasetRecord]
    test: list[PairDatasetRecord]


def repository_group_split(
    records: Iterable[PairDatasetRecord],
    *,
    train_fraction: float = 0.70,
    validation_fraction: float = 0.15,
    seed: int = 42,
) -> GroupedSplit:
    """Split by repository so versions from one codebase never leak across partitions."""

    records = list(records)
    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must be between 0 and 1")
    if not 0 <= validation_fraction < 1:
        raise ValueError("validation_fraction must be between 0 and 1")
    if train_fraction + validation_fraction >= 1:
        raise ValueError("train + validation fractions must leave room for a test split")

    grouped: dict[str, list[PairDatasetRecord]] = {}
    for record in records:
        grouped.setdefault(record.leakage_group, []).append(record)

    groups = sorted(grouped)
    Random(seed).shuffle(groups)
    n_groups = len(groups)
    train_end = int(n_groups * train_fraction)
    val_end = train_end + int(n_groups * validation_fraction)

    train_groups = set(groups[:train_end])
    validation_groups = set(groups[train_end:val_end])
    test_groups = set(groups[val_end:])

    return GroupedSplit(
        train=[r for r in records if r.leakage_group in train_groups],
        validation=[r for r in records if r.leakage_group in validation_groups],
        test=[r for r in records if r.leakage_group in test_groups],
    )


def record_features(
    record: PairDatasetRecord,
    embedding_provider: EmbeddingProvider | None = None,
    embedding_cache: EmbeddingCache | None = None,
) -> dict[str, float]:
    """Turn one labeled old/new record into a named, model-ready feature dictionary."""

    old = make_snapshot(server_id=record.server_id, tool=record.old_tool, approval_state="approved")
    new = make_snapshot(server_id=record.server_id, tool=record.new_tool)
    features = extract_pair_features(
        build_delta(old, new),
        embedding_provider=embedding_provider,
        embedding_cache=embedding_cache,
    )
    return flatten_numeric_features(features)


class LogisticPairClassifier:
    """First learned C0/C1/C2/C3 research baseline."""

    def __init__(self, *, class_weight: str | dict[str, float] | None = "balanced") -> None:
        self.class_weight = class_weight
        self._vectorizer = None
        self._model = None
        self._embedding_provider: EmbeddingProvider | None = None
        self._embedding_cache: EmbeddingCache | None = None

    def fit(
        self,
        records: Iterable[PairDatasetRecord],
        *,
        embedding_provider: EmbeddingProvider | None = None,
        embedding_cache: EmbeddingCache | None = None,
    ) -> LogisticPairClassifier:
        try:
            from sklearn.feature_extraction import DictVectorizer
            from sklearn.linear_model import LogisticRegression
            from sklearn.pipeline import Pipeline
            from sklearn.preprocessing import StandardScaler
        except ImportError as exc:
            raise RuntimeError(
                "scikit-learn is required for the learned baseline; install mcp-driftguard[ml]"
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
        y = [record.label.value for record in records]

        self._vectorizer = DictVectorizer(sparse=False)
        x = self._vectorizer.fit_transform(rows)
        self._model = Pipeline(
            [
                ("scale", StandardScaler()),
                (
                    "classifier",
                    LogisticRegression(
                        max_iter=2000,
                        class_weight=self.class_weight,
                        random_state=42,
                    ),
                ),
            ]
        )
        self._model.fit(x, y)
        return self

    def _check_fitted(self) -> None:
        if self._vectorizer is None or self._model is None:
            raise RuntimeError("Classifier has not been fitted")

    def predict_proba(self, record: PairDatasetRecord) -> dict[str, float]:
        self._check_fitted()
        row = record_features(record, self._embedding_provider, self._embedding_cache)
        x = self._vectorizer.transform([row])
        probs = self._model.predict_proba(x)[0]
        classes = self._model.named_steps["classifier"].classes_
        return {str(label): float(prob) for label, prob in zip(classes, probs, strict=True)}

    def assess(self, record: PairDatasetRecord) -> RiskAssessment:
        probabilities = self.predict_proba(record)
        predicted = max(probabilities, key=probabilities.get)
        change_class = ChangeClass(predicted)
        p_c2 = probabilities.get(ChangeClass.CAPABILITY_EXPANSION.value, 0.0)
        p_c3 = probabilities.get(ChangeClass.MALICIOUS_DRIFT.value, 0.0)
        risk_score = min(100.0, 100.0 * (0.45 * p_c2 + 1.0 * p_c3))

        if change_class is ChangeClass.MALICIOUS_DRIFT:
            action = "quarantine"
        elif change_class is ChangeClass.CAPABILITY_EXPANSION:
            action = "require_reconsent"
        elif change_class is ChangeClass.BENIGN_MAINTENANCE:
            action = "allow_and_log"
        else:
            action = "allow"

        return RiskAssessment(
            change_class=change_class,
            risk_score=round(risk_score, 2),
            probabilities={key: round(value, 6) for key, value in probabilities.items()},
            reasons=["Prediction from the first learned pairwise logistic-regression baseline."],
            recommended_action=action,
        )
