from __future__ import annotations

from collections import Counter
from dataclasses import asdict

from .calibration import binary_calibration_metrics
from .canonicalize import exact_hash
from .dataset import PairDatasetRecord
from .embeddings import EmbeddingProvider
from .evaluation import multiclass_metrics
from .learning import GroupedSplit
from .models import ChangeClass
from .tree_learning import XGBoostPairClassifier

MALICIOUS = ChangeClass.MALICIOUS_DRIFT


def validate_splits(split: GroupedSplit) -> dict[str, object]:
    groups: dict[str, str] = {}
    pairs: dict[tuple[str, ...], str] = {}
    record_ids: set[str] = set()
    summary = {}
    for name in ("train", "validation", "test"):
        records: list[PairDatasetRecord] = getattr(split, name)
        labels = Counter(record.label for record in records)
        if not labels.get(MALICIOUS) or len(labels) < 2:
            raise ValueError(f"{name} requires malicious and non-malicious examples")
        if name == "train" and labels.keys() != set(ChangeClass):
            raise ValueError("Training requires examples of all four change classes")
        repositories = {record.leakage_group for record in records}
        for repository in sorted(repositories):
            previous = groups.setdefault(repository, name)
            if previous != name:
                raise ValueError(f"Repository {repository!r} appears in {previous} and {name}")
        for record in records:
            pair = tuple(sorted((exact_hash(record.old_tool), exact_hash(record.new_tool))))
            previous = pairs.setdefault(pair, name)
            if previous != name:
                raise ValueError(f"Definition pair {record.record_id!r} appears in {previous} and {name}")
            if record.record_id in record_ids:
                raise ValueError(f"Duplicate record ID {record.record_id!r}")
            record_ids.add(record.record_id)
        summary[name] = {
            "records": len(records),
            "repositories": len(repositories),
            "labels": {label: labels[label] for label in ChangeClass},
            "provenance": dict(Counter(record.provenance for record in records)),
        }
    return summary


def _metrics(
    truth: list[ChangeClass],
    scores: list[dict[str, float]],
    threshold: float | None,
) -> dict[str, object]:
    from sklearn.metrics import average_precision_score

    predicted = [ChangeClass(max(row, key=row.__getitem__)) for row in scores]
    malicious = [label == MALICIOUS for label in truth]
    probabilities = [row[MALICIOUS] for row in scores]
    flagged = [
        label
        for label, score in zip(truth, probabilities, strict=True)
        if threshold is not None and score >= threshold
    ]
    true_positives = flagged.count(MALICIOUS)
    false_positives = len(flagged) - true_positives
    return {
        **multiclass_metrics(truth, predicted),
        "records": len(truth),
        "malicious_average_precision": float(average_precision_score(malicious, probabilities)),
        "malicious_calibration": asdict(binary_calibration_metrics(malicious, probabilities)),
        "quarantine": {
            "true_positives": true_positives,
            "false_positives": false_positives,
            "recall": true_positives / sum(malicious),
            "false_positive_rate": false_positives / (len(truth) - sum(malicious)),
            "capability_expansions_flagged": flagged.count(ChangeClass.CAPABILITY_EXPANSION),
        },
    }


def compare(
    split: GroupedSplit,
    *,
    encoder: EmbeddingProvider | None = None,
    max_false_quarantine_rate: float = 0.0,
) -> dict[str, object]:
    """Compare XGBoost on identical splits with validation-only threshold selection."""
    if not 0 <= max_false_quarantine_rate <= 1:
        raise ValueError("Maximum validation false-quarantine rate must be between 0 and 1")
    summary = validate_splits(split)

    from sklearn.metrics import roc_curve

    validation_truth = [record.label for record in split.validation]
    test_truth = [record.label for record in split.test]
    models = [("structured", None)]
    if encoder is not None:
        models.append(("structured_and_embeddings", encoder))
    results = {}
    for name, provider in models:
        model = XGBoostPairClassifier().fit(split.train, embedding_provider=provider)
        validation_scores = [model.predict_proba(record) for record in split.validation]
        false_rates, recalls, thresholds = roc_curve(
            [label == MALICIOUS for label in validation_truth],
            [row[MALICIOUS] for row in validation_scores],
            drop_intermediate=False,
        )
        candidates = [
            (recall, threshold)
            for false_rate, recall, threshold in zip(false_rates, recalls, thresholds, strict=True)
            if false_rate <= max_false_quarantine_rate and recall > 0
        ]
        threshold = float(max(candidates)[1]) if candidates else None
        results[name] = {
            "encoder": provider.model_id if provider is not None else None,
            "quarantine_threshold": threshold,
            "validation": _metrics(validation_truth, validation_scores, threshold),
            "test": _metrics(
                test_truth, [model.predict_proba(record) for record in split.test], threshold,
            ),
        }
    return {
        "report_version": 1,
        "validation_max_false_quarantine_rate": max_false_quarantine_rate,
        "splits": summary,
        "models": results,
    }
