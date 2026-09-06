from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, stdev

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
from driftguard.statistics import bootstrap_confidence_interval
from driftguard.thresholds import tune_margin_threshold


def _evaluate_seed(seed: int, repositories: int) -> dict[str, float | int]:
    development = build_development_poisoning_benchmark(repositories=repositories, seed=seed)
    records = [*development, *build_structural_challenge_records(development)]
    manifest = build_split_manifest(
        records,
        seed=seed,
        held_out_attack_families=("redirect_sink_injection", "safety_hint_mismatch"),
    )
    split = apply_split_manifest(records, manifest)
    detector = HybridPoisoningDetector().fit(split.train)

    validation_probabilities = detector.predict_proba(split.validation)
    selection = tune_margin_threshold(
        validation_probabilities,
        [record.label for record in split.validation],
        positive_labels=(ChangeClass.MALICIOUS_DRIFT,),
    )
    threshold = selection.threshold

    test_probabilities = detector.predict_proba(split.test)
    test_truth = [record.label is ChangeClass.MALICIOUS_DRIFT for record in split.test]
    test_pred = [score >= threshold for score in test_probabilities]
    test_metrics = binary_metrics(test_truth, test_pred)

    held_out = held_out_family_test_records(records, manifest)
    held_out_probabilities = detector.predict_proba(held_out)
    held_out_truth = [True] * len(held_out)
    held_out_pred = [score >= threshold for score in held_out_probabilities]
    held_out_metrics = binary_metrics(held_out_truth, held_out_pred) if held_out else None

    return {
        "seed": seed,
        "test_accuracy": test_metrics.accuracy,
        "test_precision": test_metrics.precision,
        "test_recall": test_metrics.recall,
        "test_f1": test_metrics.f1,
        "test_fpr": test_metrics.false_positive_rate,
        "held_out_family_recall": held_out_metrics.recall if held_out_metrics else 0.0,
        "threshold": threshold,
        "test_records": len(split.test),
        "held_out_records": len(held_out),
    }


def _summary(values: list[float]) -> dict[str, float | int]:
    ci = bootstrap_confidence_interval(values, bootstrap_samples=5000, seed=20260906)
    return {
        "mean": round(mean(values), 6),
        "std": round(stdev(values), 6) if len(values) > 1 else 0.0,
        "ci95_lower": round(ci.lower, 6),
        "ci95_upper": round(ci.upper, 6),
        "runs": len(values),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repositories", type=int, default=80)
    parser.add_argument(
        "--seeds",
        type=int,
        nargs="+",
        default=[104729, 130363, 169087, 214087, 277183],
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/repeated_seed_poisoning.json"),
    )
    args = parser.parse_args()

    runs = [_evaluate_seed(seed, args.repositories) for seed in args.seeds]
    metric_names = (
        "test_accuracy",
        "test_precision",
        "test_recall",
        "test_f1",
        "test_fpr",
        "held_out_family_recall",
    )
    aggregate = {
        metric: _summary([float(run[metric]) for run in runs])
        for metric in metric_names
    }
    payload = {
        "benchmark_kind": "controlled_repeated_seed_development_benchmark",
        "paper_claim_eligible": False,
        "warning": (
            "Repeated-seed uncertainty for engineering only. Final paper confidence intervals "
            "must use frozen real/external test sets and repository-cluster resampling."
        ),
        "repositories": args.repositories,
        "runs": runs,
        "aggregate": aggregate,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
