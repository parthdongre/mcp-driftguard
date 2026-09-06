from __future__ import annotations

from dataclasses import dataclass

from .attack_family_benchmark import AttackFamilyFold, validate_attack_family_fold
from .stateful_policy import (
    StatefulPolicyMetrics,
    StatefulPolicySelection,
    evaluate_stateful_policy,
    select_stateful_policy,
)
from .temporal import TemporalConfig
from .trajectory_benchmark import TemporalStrategy


@dataclass(frozen=True)
class StatefulFamilyStrategyEvaluation:
    held_out_family: str
    strategy: TemporalStrategy
    selection: StatefulPolicySelection
    test_metrics: StatefulPolicyMetrics


def evaluate_stateful_attack_family_holdout(
    fold: AttackFamilyFold,
    *,
    temporal_config: TemporalConfig | None = None,
    threshold_step: float = 0.05,
) -> tuple[StatefulFamilyStrategyEvaluation, ...]:
    """Evaluate an unseen attack family with re-consent baseline resets enabled."""

    validate_attack_family_fold(fold)
    results: list[StatefulFamilyStrategyEvaluation] = []
    for strategy in TemporalStrategy:
        selection = select_stateful_policy(
            list(fold.validation),
            strategy,
            temporal_config=temporal_config,
            threshold_step=threshold_step,
        )
        test_metrics = evaluate_stateful_policy(
            list(fold.test),
            strategy,
            selection.thresholds,
            temporal_config=temporal_config,
        )
        results.append(
            StatefulFamilyStrategyEvaluation(
                held_out_family=fold.held_out_family,
                strategy=strategy,
                selection=selection,
                test_metrics=test_metrics,
            )
        )
    return tuple(results)
