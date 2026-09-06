from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from driftguard.dataset import read_trajectory_jsonl
from driftguard.models import ChangeClass
from driftguard.temporal import TemporalConfig
from driftguard.trajectory_evaluation import evaluate_trajectories


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate DriftGuard's deterministic sequential baseline on labeled trajectories."
    )
    parser.add_argument("dataset", type=Path, help="TrajectoryDatasetRecord JSONL file")
    parser.add_argument("--output", type=Path, default=Path("artifacts/temporal_baseline.json"))
    parser.add_argument("--reference-drift", type=float, default=0.08)
    parser.add_argument("--cusum-threshold", type=float, default=0.55)
    parser.add_argument("--baseline-threshold", type=float, default=0.72)
    parser.add_argument("--memory-decay", type=float, default=0.98)
    parser.add_argument(
        "--malicious-only",
        action="store_true",
        help="Treat only C3 as positive onset instead of the C2+C3 consent boundary.",
    )
    args = parser.parse_args()

    trajectories = read_trajectory_jsonl(args.dataset)
    if not trajectories:
        raise SystemExit("Trajectory dataset is empty")

    positive_labels = (
        (ChangeClass.MALICIOUS_DRIFT,)
        if args.malicious_only
        else (ChangeClass.CAPABILITY_EXPANSION, ChangeClass.MALICIOUS_DRIFT)
    )
    config = TemporalConfig(
        reference_drift=args.reference_drift,
        cusum_threshold=args.cusum_threshold,
        baseline_threshold=args.baseline_threshold,
        memory_decay=args.memory_decay,
    )
    runs, metrics = evaluate_trajectories(
        trajectories,
        config=config,
        positive_labels=positive_labels,
    )

    payload = {
        "dataset": str(args.dataset),
        "positive_labels": [label.value for label in positive_labels],
        "config": asdict(config),
        "metrics": asdict(metrics),
        "runs": [asdict(run) for run in runs],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
