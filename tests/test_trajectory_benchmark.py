from driftguard.models import ChangeClass
from driftguard.trajectory_benchmark import (
    TemporalStrategy,
    compare_temporal_strategies,
    controlled_temporal_split,
    trajectory_signal_trace,
)


def test_controlled_temporal_split_is_repository_disjoint_and_balanced() -> None:
    validation, test = controlled_temporal_split()

    validation_repos = {item.repository_id for item in validation}
    test_repos = {item.repository_id for item in test}
    assert validation_repos.isdisjoint(test_repos)
    assert len(validation) == 6
    assert len(test) == 6

    expected = {
        ChangeClass.BENIGN_MAINTENANCE: 2,
        ChangeClass.CAPABILITY_EXPANSION: 2,
        ChangeClass.MALICIOUS_DRIFT: 2,
    }
    for split in (validation, test):
        counts = {label: 0 for label in expected}
        for item in split:
            counts[item.final_label] += 1
        assert counts == expected


def test_sequential_trace_exposes_cumulative_bounded_drift() -> None:
    _, test = controlled_temporal_split()
    attack = next(item for item in test if item.final_label is ChangeClass.MALICIOUS_DRIFT)

    adjacent = trajectory_signal_trace(attack, TemporalStrategy.ADJACENT_ONLY)
    baseline = trajectory_signal_trace(attack, TemporalStrategy.APPROVED_BASELINE)
    sequential = trajectory_signal_trace(attack, TemporalStrategy.SEQUENTIAL)

    assert sequential.attack_onset is not None
    assert len(adjacent.malicious_scores) == len(sequential.malicious_scores)
    assert sequential.malicious_scores[-1] > adjacent.malicious_scores[-1]
    assert baseline.malicious_scores[-1] == sequential.malicious_scores[-1]
    assert sequential.capability_scores[-1] > 0.0


def test_strategy_thresholds_are_selected_on_validation_then_applied_to_test() -> None:
    validation, test = controlled_temporal_split()
    results = compare_temporal_strategies(
        validation,
        test,
        threshold_step=0.10,
        min_malicious_detection=1.0,
        max_benign_block_rate=0.0,
        max_benign_reconsent_rate=0.0,
    )

    assert {item.strategy for item in results} == set(TemporalStrategy)
    for result in results:
        assert result.selection.thresholds.block_threshold > 0.0
        assert result.selection.thresholds.reconsent_threshold > 0.0
        assert result.validation_metrics.traces == len(validation)
        assert result.test_metrics.traces == len(test)
