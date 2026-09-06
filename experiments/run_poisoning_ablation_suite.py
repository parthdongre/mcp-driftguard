from __future__ import annotations

import argparse
import json
from pathlib import Path

from driftguard.calibration import binary_calibration_metrics
from driftguard.evaluation import binary_metrics
from driftguard.hybrid_detector import HybridPoisoningDetector
from driftguard.models import ChangeClass
from driftguard.poisoning import PoisoningDetector
from driftguard.poisoning_benchmark import build_development_poisoning_benchmark
from driftguard.poisoning_challenges import build_structural_challenge_records
from driftguard.research_baselines import PairAblationBaseline, SnapshotPoisoningBaseline
from driftguard.splits import (
    apply_split_manifest,
    build_split_manifest,
    held_out_family_test_records,
)
from driftguard.thresholds import tune_margin_threshold


def _evaluate(name, detector, split, held_out):
    detector.fit(split.train)
    validation_scores = detector.predict_proba(split.validation)
    threshold = tune_margin_threshold(
        validation_scores,
        [record.label for record in split.validation],
        positive_labels=(ChangeClass.MALICIOUS_DRIFT,),
    ).threshold

    def evaluate(records):
        scores = detector.predict_proba(records)
        truth = [record.label is ChangeClass.MALICIOUS_DRIFT for record in records]
        predictions = [score >= threshold for score in scores]
        metrics = binary_metrics(truth, predictions)
        return {
            **metrics.__dict__,
            "calibration": binary_calibration_metrics(truth, scores).__dict__,
        }

    return {
        "name": name,
        "validation_selected_threshold": threshold,
        "test": evaluate(split.test),
        "held_out_attack_families": evaluate(held_out) if held_out else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repositories", type=int, default=80)
    parser.add_argument("--seed", type=int, default=424242)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/poisoning_ablation_suite.json"),
    )
    args = parser.parse_args()

    development = build_development_poisoning_benchmark(
        repositories=args.repositories,
        seed=args.seed,
    )
    records = [*development, *build_structural_challenge_records(development)]
    manifest = build_split_manifest(
        records,
        seed=args.seed,
        held_out_attack_families=("redirect_sink_injection", "safety_hint_mismatch"),
    )
    split = apply_split_manifest(records, manifest)
    held_out = held_out_family_test_records(records, manifest)

    methods = [
        ("single_snapshot_text", SnapshotPoisoningBaseline()),
        ("pair_text_only", PairAblationBaseline("text_only")),
        ("pair_numeric_only", PairAblationBaseline("numeric_only")),
        ("pair_hybrid_learned", PoisoningDetector()),
        ("pair_hybrid_plus_invariants", HybridPoisoningDetector()),
    ]
    results = [_evaluate(name, detector, split, held_out) for name, detector in methods]
    payload = {
        "benchmark_kind": "controlled_ablation_development_benchmark",
        "paper_claim_eligible": False,
        "seed": args.seed,
        "repositories": args.repositories,
        "held_out_attack_families": manifest.held_out_attack_families,
        "warning": (
            "Development-only ablation suite. Final paper ablations must run on frozen real and "
            "independent external test sets after feature engineering ends."
        ),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
