from statistics import mean

import pytest

from driftguard.statistics import (
    cluster_bootstrap_confidence_interval,
    paired_cluster_bootstrap_difference,
)


def test_cluster_bootstrap_keeps_within_repository_records_together():
    # Record-level resampling could produce 1/4 or 3/4. Whole-cluster resampling
    # can only produce 0, 1/2, or 1 for these two homogeneous repositories.
    observed = []

    def metric(values):
        value = mean(values)
        observed.append(value)
        return value

    result = cluster_bootstrap_confidence_interval(
        [0.0, 0.0, 1.0, 1.0], ["a", "a", "b", "b"],
        statistic=metric, bootstrap_samples=100, seed=7,
    )
    assert set(observed) <= {0.0, 0.5, 1.0}
    assert result.estimate == 0.5
    assert result.clusters == 2
    assert result.observations == 4


def test_cluster_estimand_is_record_weighted_for_unequal_repositories():
    result = cluster_bootstrap_confidence_interval(
        [0.0, 1.0, 1.0, 1.0], ["small", "large", "large", "large"],
        bootstrap_samples=100,
    )
    assert result.estimate == 0.75


def test_paired_clusters_recompute_non_linear_metric_with_identical_resamples():
    def spread(values):
        return max(values) - min(values)

    interval = paired_cluster_bootstrap_difference(
        [0.0, 1.0, 2.0], [3.0, 4.0, 5.0], ["a", "b", "c"],
        statistic=spread, bootstrap_samples=100, seed=9,
    )
    # A translation changes means by three, but changes spread by zero.
    assert interval.estimate == interval.lower == interval.upper == 0.0


def test_cluster_resampling_is_reproducible():
    kwargs = {"bootstrap_samples": 100, "seed": 11}
    assert cluster_bootstrap_confidence_interval([0.1, 0.8], ["a", "b"], **kwargs) == (
        cluster_bootstrap_confidence_interval([0.1, 0.8], ["a", "b"], **kwargs)
    )


def test_cluster_uncertainty_requires_multiple_groups():
    with pytest.raises(ValueError, match="at least two"):
        cluster_bootstrap_confidence_interval([0.0, 1.0], ["same", "same"])
