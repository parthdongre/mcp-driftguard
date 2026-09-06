from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

from driftguard.calibration import binary_calibration_metrics
from driftguard.evaluation import binary_metrics
from driftguard.hybrid_detector import HybridPoisoningDetector
from driftguard.models import ChangeClass
from driftguard.poisoning_benchmark import build_development_poisoning_benchmark
from driftguard.poisoning_challenges import build_structural_challenge_records
from driftguard.splits import (
    apply_split_manifest,
    build_split_manifest,
    held_out_family_test_records,
)
from driftguard.thresholds import tune_margin_threshold


def _truth(records):
    return [record.label is ChangeClass.MALICIOUS_DRIFT for record in records]


def _metrics(records, probabilities, threshold):
    truth = _truth(records)
    predicted = [score >= threshold for score in probabilities]
    result = binary_metrics(truth, predicted)
    payload = result.__dict__.copy()
    try:
        from sklearn.metrics import balanced_accuracy_score, roc_auc_score

        if len(set(truth)) > 1:
            payload["balanced_accuracy"] = round(
                float(balanced_accuracy_score(truth, predicted)), 6
            )
            payload["roc_auc"] = round(float(roc_auc_score(truth, probabilities)), 6)
        else:
            payload["balanced_accuracy"] = None
            payload["roc_auc"] = None
    except (ImportError, ValueError):
        payload["balanced_accuracy"] = None
        payload["roc_auc"] = None
    return payload


def _calibration(records, probabilities):
    if not records:
        return None
    return binary_calibration_metrics(_truth(records), probabilities).__dict__


def _family_stats(records, probabilities, threshold):
    buckets = defaultdict(list)
    for record, probability in zip(records, probabilities, strict=True):
        family = record.attack_family or f"negative:{record.label.value}"
        buckets[family].append(float(probability))

    result = {}
    for family, values in sorted(buckets.items()):
        result[family] = {
            "count": len(values),
            "min_probability": round(min(values), 6),
            "mean_probability": round(sum(values) / len(values), 6),
            "max_probability": round(max(values), 6),
            "alert_rate": round(sum(value >= threshold for value in values) / len(values), 6),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repositories", type=int, default=80)
    parser.add_argument("--seed", type=int, default=314159)
    parser.add_argument("--output", type=Path, default=Path("artifacts/poisoning_benchmark.json"))
    parser.add_argument(
        "--held-out-family",
        action="append",
        default=[
            "redirect_sink_injection",
            "safety_hint_mismatch",
        ],
    )
    args = parser.parse_args()

    development_records = build_development_poisoning_benchmark(
        repositories=args.repositories,
        seed=args.seed,
    )
    records = [
        *development_records,
        *build_structural_challenge_records(development_records),
    ]
    manifest = build_split_manifest(
        records,
        seed=args.seed,
        held_out_attack_families=args.held_out_family,
    )
    split = apply_split_manifest(records, manifest)

    detector = HybridPoisoningDetector().fit(split.train)
    validation_probabilities = detector.predict_proba(split.validation)
    threshold_selection = tune_margin_threshold(
        validation_probabilities,
        [record.label for record in split.validation],
        positive_labels=(ChangeClass.MALICIOUS_DRIFT,),
    )
    calibrated_threshold = threshold_selection.threshold
    fixed_threshold = 0.5

    test_probabilities = detector.predict_proba(split.test)
    held_out = held_out_family_test_records(records, manifest)
    held_out_probabilities = detector.predict_proba(held_out)

    result = {
        "benchmark_kind": "controlled_development_benchmark",
        "benchmark_protocol": "fresh_structural_holdout_v1",
        "detector": "hybrid_ml_plus_structural_invariants",
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
        "validation_calibration": {
            "method": threshold_selection.objective,
            "threshold": calibrated_threshold,
            "separation_margin": threshold_selection.objective_value,
            "threshold_metrics": threshold_selection.metrics.__dict__,
            "probability_calibration": _calibration(
                split.validation, validation_probabilities
            ),
        },
        "validation_fixed_0_5_metrics": _metrics(
            split.validation, validation_probabilities, fixed_threshold
        ),
        "test_calibrated_metrics": _metrics(
            split.test, test_probabilities, calibrated_threshold
        ),
        "test_fixed_0_5_metrics": _metrics(split.test, test_probabilities, fixed_threshold),
        "test_probability_calibration": _calibration(split.test, test_probabilities),
        "held_out_calibrated_metrics": (
            _metrics(held_out, held_out_probabilities, calibrated_threshold) if held_out else None
        ),
        "held_out_fixed_0_5_metrics": (
            _metrics(held_out, held_out_probabilities, fixed_threshold) if held_out else None
        ),
        "held_out_probability_calibration": _calibration(held_out, held_out_probabilities),
        "test_family_probability_stats": _family_stats(
            split.test, test_probabilities, calibrated_threshold
        ),
    }

    def scrub(value):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    result = scrub(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
