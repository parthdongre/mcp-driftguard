from __future__ import annotations

from .attack_family_benchmark import AttackFamilyFold
from .learned_family_benchmark import (
    LearnedFamilyEvaluation,
    LearnedFamilyStrategyEvaluation,
    evaluate_prepared_policy,
    pair_classification_metrics,
    prepare_learned_trajectory,
    select_learned_policy,
    split_attack_family_fold,
    trajectory_adjacent_pairs,
    trajectory_training_pairs,
)
from .trajectory_benchmark import TemporalStrategy
from .tree_learning import XGBoostPairClassifier


def evaluate_xgboost_family_fold(
    fold: AttackFamilyFold,
) -> LearnedFamilyEvaluation:
    """Evaluate XGBoost with the same repository/family partitions as logistic."""

    split = split_attack_family_fold(fold)
    training_records = [
        record
        for trajectory in split.train
        for record in trajectory_training_pairs(trajectory)
    ]
    model = XGBoostPairClassifier().fit(training_records)

    policy_prepared = [
        prepare_learned_trajectory(model, item)
        for item in split.policy_validation
    ]
    test_prepared = [
        prepare_learned_trajectory(model, item)
        for item in split.test
    ]
    strategies: list[LearnedFamilyStrategyEvaluation] = []
    for strategy in TemporalStrategy:
        selection = select_learned_policy(policy_prepared, strategy)
        test_metrics = evaluate_prepared_policy(
            test_prepared,
            strategy,
            selection.thresholds,
        )
        strategies.append(
            LearnedFamilyStrategyEvaluation(
                held_out_family=fold.held_out_family,
                strategy=strategy,
                selection=selection,
                policy_validation_metrics=selection.metrics,
                test_metrics=test_metrics,
            )
        )

    test_records = [
        record
        for trajectory in split.test
        for record in trajectory_adjacent_pairs(trajectory)
    ]
    return LearnedFamilyEvaluation(
        held_out_family=fold.held_out_family,
        train_repositories=tuple(sorted({item.repository_id for item in split.train})),
        policy_validation_repositories=tuple(
            sorted({item.repository_id for item in split.policy_validation})
        ),
        test_repositories=tuple(sorted({item.repository_id for item in split.test})),
        pair_metrics=pair_classification_metrics(model, test_records),
        strategies=tuple(strategies),
    )
