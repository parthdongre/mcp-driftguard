from __future__ import annotations

import json
from dataclasses import asdict
from statistics import mean

from driftguard.attack_family_benchmark import (
    MALICIOUS_ATTACK_FAMILIES,
    bounded_audits,
    controlled_attack_family_folds,
    evaluate_attack_family_holdout,
)
from driftguard.attack_family_stateful import evaluate_stateful_attack_family_holdout
from driftguard.trajectory_benchmark import TemporalStrategy


def main() -> None:
    folds = controlled_attack_family_folds()
    fold_payloads = []
    stateful_by_strategy: dict[str, list[float]] = {
        strategy.value: [] for strategy in TemporalStrategy
    }

    for fold in folds:
        stateful = evaluate_stateful_attack_family_holdout(fold)
        static = evaluate_attack_family_holdout(fold)
        for result in stateful:
            stateful_by_strategy[result.strategy.value].append(
                result.test_metrics.malicious_post_onset_block_rate
            )

        fold_payloads.append(
            {
                "held_out_family": fold.held_out_family,
                "validation_repositories": sorted(
                    {item.repository_id for item in fold.validation}
                ),
                "test_repositories": sorted({item.repository_id for item in fold.test}),
                "validation_trajectories": len(fold.validation),
                "test_trajectories": len(fold.test),
                "bounded_test_attack_audits": [
                    asdict(report) for report in bounded_audits(fold)
                ],
                "stateful_consent_reset_strategies": [
                    {
                        "strategy": result.strategy.value,
                        "selected_thresholds": asdict(result.selection.thresholds),
                        "selection_objective": result.selection.objective,
                        "selection_feasible": result.selection.feasible,
                        "validation_metrics": asdict(result.selection.metrics),
                        "test_metrics": asdict(result.test_metrics),
                    }
                    for result in stateful
                ],
                "static_no_reset_diagnostic": [
                    {
                        "strategy": result.strategy.value,
                        "selected_thresholds": asdict(result.selection.thresholds),
                        "strict_unseen_family_metrics": asdict(
                            result.strict_unseen_family_metrics
                        ),
                    }
                    for result in static
                ],
            }
        )

    summary = {
        strategy: {
            "mean_stateful_post_onset_block_rate": round(mean(values), 6),
            "worst_family_stateful_post_onset_block_rate": round(min(values), 6),
        }
        for strategy, values in stateful_by_strategy.items()
    }

    payload = {
        "benchmark_kind": "controlled_repository_and_attack_family_disjoint_bounded_drift",
        "paper_claim_eligible": False,
        "attack_families": list(MALICIOUS_ATTACK_FAMILIES),
        "primary_evaluation": "stateful_consent_reset",
        "warning": (
            "This is a controlled leave-one-attack-family-out development benchmark. "
            "Thresholds are selected only on repository-disjoint validation trajectories "
            "from other controlled families. Results test methodology and leakage controls; "
            "they are not independent real-world or publication evidence."
        ),
        "stateful_metric_note": (
            "The primary evaluation treats C2 re-consent as a new approved baseline and "
            "resets sequential memory before later versions. This prevents an obsolete "
            "pre-consent snapshot from making unseen-family detection look artificially easy."
        ),
        "static_diagnostic_note": (
            "The static no-reset trace is retained only as a diagnostic upper bound. It can "
            "show post-onset risk above threshold even when the operational policy would "
            "already have re-consented and reset its baseline."
        ),
        "summary": summary,
        "folds": fold_payloads,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
