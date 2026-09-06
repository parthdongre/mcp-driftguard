from __future__ import annotations

import argparse
import json
from pathlib import Path

from driftguard.evaluation import binary_metrics
from driftguard.models import ChangeClass
from driftguard.poisoning import PoisoningDetector
from driftguard.poisoning_benchmark import build_development_poisoning_benchmark
from driftguard.splits import (
    apply_split_manifest,
    build_split_manifest,
    held_out_family_test_records,
)
from driftguard.thresholds import tune_binary_threshold


def _metrics(records, probabilities, threshold):
    truth = [record.label is ChangeClass.MALICIOUS_DRIFT for record in records]
    predicted = [score >= threshold for score in probabilities]
    result = binary_metrics(truth, predicted)
    payload = result.__dict__.copy()
    try:
        from sklearn.metrics import balanced_accuracy_score, roc_auc_score

        payload["balanced_accuracy"] = round(
            float(balanced_accuracy_score(truth, predicted)), 6
        )
        payload["roc_auc"] = round(float(roc_auc_score(truth, probabilities)), 6)
    except (ImportError, ValueError):
        payload["balanced_accuracy"] = None
        payload["roc_auc"] = None
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repositories", type=int, default=80)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=Path("artifacts/poisoning_benchmark.json"))
    parser.add_argument(
        "--held-out-family",
        action="append",
        default=["paraphrased_override", "unicode_concealment", "default_endpoint_hijack"],
    )
    args = parser.parse_args()

    records = build_development_poisoning_benchmark(
        repositories=args.repositories,
        seed=args.seed,
    )
    manifest = build_split_manifest(
        records,
        seed=args.seed,
        held_out_attack_families=args.held_out_family,
    )
    split = apply_split_manifest(records, manifest)

    detector = PoisoningDetector().fit(split.train)
    validation_probabilities = detector.predict_proba(split.validation)
    threshold_selection = tune_binary_threshold(
        validation_probabilities,
        [record.label for record in split.validation],
        positive_labels=(ChangeClass.MALICIOUS_DRIFT,),
        objective="f1",
    )
    threshold = threshold_selection.threshold

    test_probabilities = detector.predict_proba(split.test)
    held_out = held_out_family_test_records(records, manifest)
    held_out_probabilities = detector.predict_proba(held_out)

    result = {
        "benchmark_kind": "controlled_development_benchmark",
        "paper_claim_eligible": False,
        "warning": (
            "Synthetic/development result only. Do not report this accuracy as real-world MCP "
            "poisoning accuracy; paper claims require independent real labels/incidents."
        ),
        "seed": args.seed,
        "records": len(records),
        "repositories": args.repositories,
        "train_records": len(split.train),
        "validation_records": len(split.validation),
        "test_records": len(split.test),
        "held_out_attack_families": manifest.held_out_attack_families,
        "held_out_family_test_records": len(held_out),
        "validation_threshold": threshold,
        "validation_metrics": threshold_selection.metrics.__dict__,
        "test_metrics": _metrics(split.test, test_probabilities, threshold),
        "held_out_family_metrics": (
            _metrics(held_out, held_out_probabilities, threshold) if held_out else None
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
