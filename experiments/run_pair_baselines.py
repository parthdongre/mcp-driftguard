from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from driftguard.dataset import read_pair_jsonl
from driftguard.evaluation import evaluate_binary_baseline, evaluate_standard_baselines
from driftguard.learning import LogisticPairClassifier, repository_group_split
from driftguard.models import ChangeClass


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run DriftGuard pairwise baselines on a repository-disjoint test split."
    )
    parser.add_argument("dataset", type=Path, help="PairDatasetRecord JSONL file")
    parser.add_argument("--output", type=Path, default=Path("artifacts/pair_baselines.json"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--lexical-threshold", type=float, default=0.12)
    parser.add_argument("--rule-threshold", type=float, default=45.0)
    parser.add_argument(
        "--train-logistic",
        action="store_true",
        help="Train the first C0-C3 logistic baseline (requires scikit-learn).",
    )
    args = parser.parse_args()

    records = read_pair_jsonl(args.dataset)
    split = repository_group_split(records, seed=args.seed)
    if not split.test:
        raise SystemExit("Test split is empty; add more repository groups or adjust the split.")

    standard = evaluate_standard_baselines(
        split.test,
        lexical_threshold=args.lexical_threshold,
        rule_threshold=args.rule_threshold,
    )
    malicious_only = [
        evaluate_binary_baseline(
            result.name,
            split.test,
            {
                "hash_any_change": lambda r: r.old_tool != r.new_tool,
                "lexical_threshold": lambda r: __import__(
                    "driftguard.evaluation", fromlist=["lexical_alert"]
                ).lexical_alert(r, threshold=args.lexical_threshold),
                "rule_risk": lambda r: __import__(
                    "driftguard.evaluation", fromlist=["rule_alert"]
                ).rule_alert(r, risk_threshold=args.rule_threshold),
            }[result.name],
            positive_labels=(ChangeClass.MALICIOUS_DRIFT,),
        )
        for result in standard
    ]

    payload: dict[str, object] = {
        "dataset": str(args.dataset),
        "seed": args.seed,
        "split": {
            "train_records": len(split.train),
            "validation_records": len(split.validation),
            "test_records": len(split.test),
            "train_repositories": len({r.repository_id for r in split.train}),
            "validation_repositories": len({r.repository_id for r in split.validation}),
            "test_repositories": len({r.repository_id for r in split.test}),
        },
        "consent_significant_c2_c3": [
            {"name": result.name, "metrics": asdict(result.metrics)} for result in standard
        ],
        "malicious_only_c3": [
            {"name": result.name, "metrics": asdict(result.metrics)} for result in malicious_only
        ],
    }

    if args.train_logistic:
        if not split.train:
            raise SystemExit("Training split is empty")
        classifier = LogisticPairClassifier().fit(split.train)
        predictions = [classifier.assess(record).change_class for record in split.test]
        from driftguard.evaluation import multiclass_metrics

        payload["logistic_pair_classifier"] = multiclass_metrics(
            [record.label for record in split.test],
            predictions,
        )

    _write_json(args.output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
