from __future__ import annotations

import json
from dataclasses import asdict

from driftguard.bounded_drift import analyze_bounded_trajectory
from driftguard.models import ChangeClass
from driftguard.trajectory_benchmark import (
    TemporalStrategy,
    compare_temporal_strategies,
    controlled_temporal_split,
    trajectory_signal_trace,
)


def _trace_payload(trajectory, strategy):
    trace = trajectory_signal_trace(trajectory, strategy)
    return {
        "trajectory_id": trajectory.trajectory_id,
        "repository_id": trajectory.repository_id,
        "final_label": trajectory.final_label.value,
        "attack_onset": trace.attack_onset,
        "malicious_scores": list(trace.malicious_scores),
        "capability_scores": list(trace.capability_scores),
    }


def main() -> None:
    validation, test = controlled_temporal_split()
    evaluations = compare_temporal_strategies(validation, test)

    bounded_audits = []
    for trajectory in validation + test:
        if trajectory.final_label is not ChangeClass.MALICIOUS_DRIFT:
            continue
        report = analyze_bounded_trajectory(trajectory)
        bounded_audits.append(asdict(report))

    payload = {
        "benchmark_kind": "controlled_temporal_development_benchmark",
        "paper_claim_eligible": False,
        "warning": (
            "Thresholds are selected on repository-disjoint controlled validation lineages, "
            "then applied once to controlled test lineages. These results validate the temporal "
            "methodology and plumbing; they are not independent real-world evidence."
        ),
        "validation_trajectories": len(validation),
        "test_trajectories": len(test),
        "validation_repositories": sorted({item.repository_id for item in validation}),
        "test_repositories": sorted({item.repository_id for item in test}),
        "bounded_attack_audits": bounded_audits,
        "strategies": [
            {
                "strategy": result.strategy.value,
                "selected_thresholds": asdict(result.selection.thresholds),
                "selection_objective": result.selection.objective,
                "selection_feasible": result.selection.feasible,
                "validation_metrics": asdict(result.validation_metrics),
                "test_metrics": asdict(result.test_metrics),
            }
            for result in evaluations
        ],
        "test_signal_traces": {
            strategy.value: [_trace_payload(item, strategy) for item in test]
            for strategy in TemporalStrategy
        },
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
