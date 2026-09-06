from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from driftguard.dataset import read_pair_jsonl
from driftguard.embeddings import EmbeddingCache, SentenceTransformerProvider
from driftguard.evaluation import evaluate_semantic_baselines, semantic_drift_scores
from driftguard.models import ChangeClass
from driftguard.splits import apply_split_manifest, read_split_manifest
from driftguard.thresholds import tune_binary_threshold


def _validation_scores(records, provider, cache):
    full_schema: list[float] = []
    field_aware: list[float] = []
    for record in records:
        scores = semantic_drift_scores(
            record,
            embedding_provider=provider,
            embedding_cache=cache,
        )
        full_schema.append(scores.get("full_schema", 0.0))
        field_aware.append(max(scores.values(), default=0.0))
    return full_schema, field_aware


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare full-schema and field-aware cosine baselines on a frozen test split."
    )
    parser.add_argument("dataset", type=Path, help="PairDatasetRecord JSONL file")
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts/semantic_baselines.json"))
    parser.add_argument(
        "--model",
        default="sentence-transformers/all-MiniLM-L6-v2",
        help="Local sentence-transformers model identifier",
    )
    parser.add_argument("--full-schema-threshold", type=float, default=0.20)
    parser.add_argument("--field-threshold", type=float, default=0.20)
    parser.add_argument(
        "--fixed-thresholds",
        action="store_true",
        help="Use supplied thresholds instead of selecting them on validation data.",
    )
    args = parser.parse_args()

    records = read_pair_jsonl(args.dataset)
    manifest = read_split_manifest(args.split_manifest)
    split = apply_split_manifest(records, manifest)
    if not split.test:
        raise SystemExit("Frozen test split is empty")

    provider = SentenceTransformerProvider(args.model)
    cache = EmbeddingCache()

    consent_thresholds = {
        "full_schema": args.full_schema_threshold,
        "field_aware": args.field_threshold,
    }
    malicious_thresholds = dict(consent_thresholds)
    threshold_selection: dict[str, object] = {"mode": "fixed"}

    if not args.fixed_thresholds:
        if not split.validation:
            raise SystemExit(
                "Validation split is empty; provide more repository groups or use --fixed-thresholds."
            )
        full_values, field_values = _validation_scores(split.validation, provider, cache)
        validation_labels = [record.label for record in split.validation]

        consent_full = tune_binary_threshold(full_values, validation_labels)
        consent_field = tune_binary_threshold(field_values, validation_labels)
        malicious_full = tune_binary_threshold(
            full_values,
            validation_labels,
            positive_labels=(ChangeClass.MALICIOUS_DRIFT,),
        )
        malicious_field = tune_binary_threshold(
            field_values,
            validation_labels,
            positive_labels=(ChangeClass.MALICIOUS_DRIFT,),
        )
        consent_thresholds = {
            "full_schema": consent_full.threshold,
            "field_aware": consent_field.threshold,
        }
        malicious_thresholds = {
            "full_schema": malicious_full.threshold,
            "field_aware": malicious_field.threshold,
        }
        threshold_selection = {
            "mode": "validation_f1",
            "validation_records": len(split.validation),
            "consent_significant_c2_c3": {
                "full_schema": asdict(consent_full),
                "field_aware": asdict(consent_field),
            },
            "malicious_only_c3": {
                "full_schema": asdict(malicious_full),
                "field_aware": asdict(malicious_field),
            },
        }

    consent_results = evaluate_semantic_baselines(
        split.test,
        embedding_provider=provider,
        embedding_cache=cache,
        full_schema_threshold=consent_thresholds["full_schema"],
        field_threshold=consent_thresholds["field_aware"],
    )
    malicious_results = evaluate_semantic_baselines(
        split.test,
        embedding_provider=provider,
        embedding_cache=cache,
        full_schema_threshold=malicious_thresholds["full_schema"],
        field_threshold=malicious_thresholds["field_aware"],
        positive_labels=(ChangeClass.MALICIOUS_DRIFT,),
    )

    payload = {
        "dataset": str(args.dataset),
        "split_manifest": str(args.split_manifest),
        "model": args.model,
        "validation_records": len(split.validation),
        "test_records": len(split.test),
        "threshold_selection": threshold_selection,
        "test_thresholds": {
            "consent_significant_c2_c3": consent_thresholds,
            "malicious_only_c3": malicious_thresholds,
        },
        "consent_significant_c2_c3": [
            {"name": result.name, "metrics": asdict(result.metrics)}
            for result in consent_results
        ],
        "malicious_only_c3": [
            {"name": result.name, "metrics": asdict(result.metrics)}
            for result in malicious_results
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
