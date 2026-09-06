from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .baselines import hash_only_changed, rule_baseline
from .canonicalize import make_snapshot
from .dataset import PairDatasetRecord
from .diff import build_delta
from .embeddings import EmbeddingCache, EmbeddingProvider
from .features import extract_pair_features
from .models import ChangeClass


@dataclass(frozen=True)
class BinaryMetrics:
    tp: int
    fp: int
    tn: int
    fn: int
    precision: float
    recall: float
    f1: float
    false_positive_rate: float
    accuracy: float


@dataclass(frozen=True)
class BaselineResult:
    name: str
    positive_labels: tuple[ChangeClass, ...]
    metrics: BinaryMetrics


def _safe_div(num: float, den: float) -> float:
    return num / den if den else 0.0


def binary_metrics(y_true: Iterable[bool], y_pred: Iterable[bool]) -> BinaryMetrics:
    truth = list(y_true)
    pred = list(y_pred)
    if len(truth) != len(pred):
        raise ValueError("y_true and y_pred must have equal length")
    if not truth:
        raise ValueError("At least one evaluation example is required")

    tp = sum(t and p for t, p in zip(truth, pred, strict=True))
    fp = sum((not t) and p for t, p in zip(truth, pred, strict=True))
    tn = sum((not t) and (not p) for t, p in zip(truth, pred, strict=True))
    fn = sum(t and (not p) for t, p in zip(truth, pred, strict=True))
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    fpr = _safe_div(fp, fp + tn)
    accuracy = _safe_div(tp + tn, len(truth))
    return BinaryMetrics(
        tp=tp,
        fp=fp,
        tn=tn,
        fn=fn,
        precision=round(precision, 6),
        recall=round(recall, 6),
        f1=round(f1, 6),
        false_positive_rate=round(fpr, 6),
        accuracy=round(accuracy, 6),
    )


def _delta(record: PairDatasetRecord):
    old = make_snapshot(server_id=record.server_id, tool=record.old_tool, approval_state="approved")
    new = make_snapshot(server_id=record.server_id, tool=record.new_tool)
    return build_delta(old, new)


def hash_alert(record: PairDatasetRecord) -> bool:
    return hash_only_changed(_delta(record))


def rule_alert(record: PairDatasetRecord, *, risk_threshold: float = 45.0) -> bool:
    return rule_baseline(_delta(record)).risk_score >= risk_threshold


def lexical_alert(record: PairDatasetRecord, *, threshold: float = 0.12) -> bool:
    return _delta(record).lexical_change_ratio >= threshold


def semantic_drift_scores(
    record: PairDatasetRecord,
    *,
    embedding_provider: EmbeddingProvider,
    embedding_cache: EmbeddingCache | None = None,
) -> dict[str, float]:
    """Return all five field-aware semantic cosine distances for one version pair."""

    features = extract_pair_features(
        _delta(record),
        embedding_provider=embedding_provider,
        embedding_cache=embedding_cache,
    )
    return features.view_semantic_drift


def full_schema_semantic_alert(
    record: PairDatasetRecord,
    *,
    embedding_provider: EmbeddingProvider,
    embedding_cache: EmbeddingCache | None = None,
    threshold: float = 0.20,
) -> bool:
    """Cosine baseline that embeds only the full canonical schema view."""

    scores = semantic_drift_scores(
        record,
        embedding_provider=embedding_provider,
        embedding_cache=embedding_cache,
    )
    return scores.get("full_schema", 0.0) >= threshold


def field_semantic_alert(
    record: PairDatasetRecord,
    *,
    embedding_provider: EmbeddingProvider,
    embedding_cache: EmbeddingCache | None = None,
    threshold: float = 0.20,
) -> bool:
    """Field-aware cosine baseline that alerts when any schema view crosses threshold."""

    scores = semantic_drift_scores(
        record,
        embedding_provider=embedding_provider,
        embedding_cache=embedding_cache,
    )
    return max(scores.values(), default=0.0) >= threshold


def evaluate_binary_baseline(
    name: str,
    records: Iterable[PairDatasetRecord],
    predictor: Callable[[PairDatasetRecord], bool],
    *,
    positive_labels: tuple[ChangeClass, ...] = (
        ChangeClass.CAPABILITY_EXPANSION,
        ChangeClass.MALICIOUS_DRIFT,
    ),
) -> BaselineResult:
    records = list(records)
    positives = set(positive_labels)
    truth = [record.label in positives for record in records]
    predictions = [bool(predictor(record)) for record in records]
    return BaselineResult(
        name=name,
        positive_labels=positive_labels,
        metrics=binary_metrics(truth, predictions),
    )


def evaluate_standard_baselines(
    records: Iterable[PairDatasetRecord],
    *,
    lexical_threshold: float = 0.12,
    rule_threshold: float = 45.0,
) -> list[BaselineResult]:
    """Evaluate dependency-free baseline detectors on a shared record list."""

    records = list(records)
    return [
        evaluate_binary_baseline("hash_any_change", records, hash_alert),
        evaluate_binary_baseline(
            "lexical_threshold",
            records,
            lambda record: lexical_alert(record, threshold=lexical_threshold),
        ),
        evaluate_binary_baseline(
            "rule_risk",
            records,
            lambda record: rule_alert(record, risk_threshold=rule_threshold),
        ),
    ]


def evaluate_semantic_baselines(
    records: Iterable[PairDatasetRecord],
    *,
    embedding_provider: EmbeddingProvider,
    embedding_cache: EmbeddingCache | None = None,
    full_schema_threshold: float = 0.20,
    field_threshold: float = 0.20,
    positive_labels: tuple[ChangeClass, ...] = (
        ChangeClass.CAPABILITY_EXPANSION,
        ChangeClass.MALICIOUS_DRIFT,
    ),
) -> list[BaselineResult]:
    """Compare full-schema-only and field-aware cosine baselines on identical records."""

    records = list(records)
    cache = embedding_cache or EmbeddingCache()
    return [
        evaluate_binary_baseline(
            "full_schema_cosine",
            records,
            lambda record: full_schema_semantic_alert(
                record,
                embedding_provider=embedding_provider,
                embedding_cache=cache,
                threshold=full_schema_threshold,
            ),
            positive_labels=positive_labels,
        ),
        evaluate_binary_baseline(
            "field_aware_cosine",
            records,
            lambda record: field_semantic_alert(
                record,
                embedding_provider=embedding_provider,
                embedding_cache=cache,
                threshold=field_threshold,
            ),
            positive_labels=positive_labels,
        ),
    ]


def multiclass_metrics(
    y_true: Iterable[ChangeClass],
    y_pred: Iterable[ChangeClass],
) -> dict[str, object]:
    """Compute paper-ready multiclass metrics when scikit-learn is installed."""

    try:
        from sklearn.metrics import (
            accuracy_score,
            classification_report,
            confusion_matrix,
            f1_score,
        )
    except ImportError as exc:
        raise RuntimeError(
            "scikit-learn is required for multiclass metrics; install mcp-driftguard[ml]"
        ) from exc

    truth = [label.value for label in y_true]
    pred = [label.value for label in y_pred]
    labels = [label.value for label in ChangeClass]
    return {
        "accuracy": float(accuracy_score(truth, pred)),
        "macro_f1": float(f1_score(truth, pred, labels=labels, average="macro", zero_division=0)),
        "classification_report": classification_report(
            truth,
            pred,
            labels=labels,
            output_dict=True,
            zero_division=0,
        ),
        "confusion_matrix": confusion_matrix(truth, pred, labels=labels).tolist(),
        "labels": labels,
    }
