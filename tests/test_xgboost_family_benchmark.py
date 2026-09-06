from __future__ import annotations

import pytest

pytest.importorskip("sklearn")
pytest.importorskip("xgboost")

from driftguard.attack_family_benchmark import controlled_attack_family_folds
from driftguard.xgboost_family_benchmark import evaluate_xgboost_family_fold


def test_xgboost_family_holdout_smoke() -> None:
    result = evaluate_xgboost_family_fold(controlled_attack_family_folds()[0])

    assert result.pair_metrics.records > 0
    assert 0.0 <= result.pair_metrics.macro_f1 <= 1.0
    assert len(result.strategies) == 3
    assert set(result.train_repositories).isdisjoint(result.policy_validation_repositories)
    assert set(result.train_repositories).isdisjoint(result.test_repositories)
