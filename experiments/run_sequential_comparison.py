"""Small controlled comparison, not independent MCP security evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
from pathlib import Path
from statistics import mean, pstdev

from driftguard.canonicalize import make_snapshot
from driftguard.diff import build_delta
from driftguard.features import extract_pair_features
from driftguard.models import ChangeClass
from driftguard.sequential_experiments import EWMAChart, MultivariateCUSUM
from driftguard.temporal import research_risk_signal
from driftguard.trajectory_benchmark import controlled_temporal_split


def _features(trajectory):
    approved_index = next(
        index for index, item in enumerate(trajectory.steps)
        if item.version_id == trajectory.approved_version_id
    )
    approved = make_snapshot(
        server_id=trajectory.server_id, tool=trajectory.steps[approved_index].tool,
    )
    previous = approved
    values = []
    for item in trajectory.steps[approved_index + 1:]:
        current = make_snapshot(server_id=trajectory.server_id, tool=item.tool)
        local = extract_pair_features(build_delta(previous, current))
        baseline = extract_pair_features(build_delta(approved, current))
        values.append((research_risk_signal(local), baseline.capability_escalation_score))
        previous = current
    return values


def run_comparison():
    validation, test = controlled_temporal_split()
    benign = [
        value for item in validation
        if item.final_label in {ChangeClass.NO_MEANINGFUL_CHANGE, ChangeClass.BENIGN_MAINTENANCE}
        for value in _features(item)
    ]
    reference_mean = tuple(mean(row[index] for row in benign) for index in range(2))
    reference_scale = tuple(max(0.05, pstdev(row[index] for row in benign)) for index in range(2))

    def scores(item, method):
        values = _features(item)
        if method == "adjacent_risk":
            return [row[0] for row in values]
        if method == "ewma":
            chart = EWMAChart(alpha=0.5, reference_mean=reference_mean[0])
            return [chart.observe(row[0]).score for row in values]
        chart = MultivariateCUSUM(reference_mean, reference_scale, allowance=0.5)
        return [chart.observe(row).score for row in values]

    results = []
    for method in ("adjacent_risk", "ewma", "multivariate_cusum"):
        validation_scores = {item.trajectory_id: scores(item, method) for item in validation}
        # C2 is reported separately, not mislabeled as benign C0/C1 or malicious C3.
        negative = [item for item in validation if item.final_label is ChangeClass.BENIGN_MAINTENANCE]
        threshold = max(
            max(validation_scores[item.trajectory_id]) for item in negative
        ) + 1e-6
        predictions = []
        for item in test:
            values = scores(item, method)
            onset = next((
                index for index, step in enumerate(item.steps[1:]) if step.attack_family
            ), None) if item.final_label is ChangeClass.MALICIOUS_DRIFT else None
            first_alert = next((index for index, value in enumerate(values) if value >= threshold), None)
            post_alert = next((
                index for index, value in enumerate(values)
                if onset is not None and index >= onset and value >= threshold
            ), None)
            predictions.append({
                "trajectory_id": item.trajectory_id, "repository_id": item.repository_id,
                "label": item.final_label.value, "scores": values,
                "attack_onset": onset, "first_alert": first_alert,
                "first_post_onset_alert": post_alert,
                "pre_onset_false_alarm": first_alert is not None and onset is not None and first_alert < onset,
            })
        attacks = [item for item in predictions if item["attack_onset"] is not None]
        benign_predictions = [item for item in predictions if item["label"] in {"C0", "C1"}]
        delays = [
            item["first_post_onset_alert"] - item["attack_onset"] for item in attacks
            if item["first_post_onset_alert"] is not None
        ]
        results.append({
            "method": method, "validation_selected_threshold": threshold,
            "threshold_selection": "strictly above maximum benign validation score; no test tuning",
            "detected_malicious_trajectories": sum(item["first_post_onset_alert"] is not None for item in attacks),
            "malicious_trajectories": len(attacks),
            "benign_false_alarm_trajectories": sum(item["first_alert"] is not None for item in benign_predictions),
            "benign_trajectories": len(benign_predictions),
            "pre_onset_false_alarm_trajectories": sum(item["pre_onset_false_alarm"] for item in attacks),
            "mean_post_onset_detection_delay": mean(delays) if delays else None,
            "c2_intervention_trajectories": sum(
                item["label"] == "C2" and item["first_alert"] is not None for item in predictions
            ),
            "predictions": predictions,
        })
    return {
        "benchmark_kind": "controlled_sequential_plumbing_comparison",
        "paper_claim_eligible": False,
        "warning": "Tiny templated development corpus; no human labels, independent attack evidence, or distribution guarantees.",
        "reference_source": "benign validation lineages only",
        "reference_mean": reference_mean, "reference_scale": reference_scale,
        "validation_repositories": sorted({item.repository_id for item in validation}),
        "test_repositories": sorted({item.repository_id for item in test}),
        "methods": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/sequential_comparison.json"))
    args = parser.parse_args()
    payload = run_comparison()
    payload["git_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    payload["working_tree_dirty"] = bool(subprocess.check_output(
        ["git", "status", "--porcelain"], text=True,
    ).strip())
    payload["python_version"] = platform.python_version()
    payload["source_sha256"] = {
        str(source): hashlib.sha256(source.read_bytes()).hexdigest()
        for source in sorted(Path("src/driftguard").glob("*.py"))
    }
    payload["command"] = f"PYTHONPATH=src python experiments/run_sequential_comparison.py --output {args.output}"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"artifact": str(args.output), "paper_claim_eligible": False}))


if __name__ == "__main__":
    main()
