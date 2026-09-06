from __future__ import annotations

import json
from dataclasses import asdict

from driftguard.attack_family_benchmark import controlled_attack_family_folds
from driftguard.xgboost_family_benchmark import evaluate_xgboost_family_fold


def main() -> None:
    evaluations = [
        evaluate_xgboost_family_fold(fold)
        for fold in controlled_attack_family_folds()
    ]
    payload = {
        "benchmark_kind": "controlled_xgboost_repository_and_attack_family_holdout",
        "paper_claim_eligible": False,
        "model": "xgboost_pair_classifier",
        "warning": (
            "This controlled benchmark reuses the development families and feature set. "
            "It is for model comparison only and is not independent publication evidence."
        ),
        "folds": [asdict(item) for item in evaluations],
        "summary": {
            item.held_out_family: {
                "pair_macro_f1": item.pair_metrics.macro_f1,
                "malicious_auroc": item.pair_metrics.malicious_auroc,
                "strategies": {
                    strategy.strategy.value: {
                        "selection_feasible": strategy.selection.feasible,
                        "post_onset_block_rate": strategy.test_metrics.malicious_post_onset_block_rate,
                        "c2_reconsent_rate": strategy.test_metrics.c2_reconsent_rate,
                        "benign_intervention_rate": strategy.test_metrics.benign_intervention_rate,
                        "pre_onset_block_rate": strategy.test_metrics.malicious_pre_onset_block_rate,
                    }
                    for strategy in item.strategies
                },
            }
            for item in evaluations
        },
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
