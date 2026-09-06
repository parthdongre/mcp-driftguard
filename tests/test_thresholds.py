from driftguard.models import ChangeClass
from driftguard.thresholds import tune_binary_threshold


def test_threshold_selection_uses_validation_scores_deterministically():
    values = [0.02, 0.05, 0.40, 0.80]
    labels = [
        ChangeClass.BENIGN_MAINTENANCE,
        ChangeClass.BENIGN_MAINTENANCE,
        ChangeClass.CAPABILITY_EXPANSION,
        ChangeClass.MALICIOUS_DRIFT,
    ]

    selection = tune_binary_threshold(values, labels, objective="f1")

    assert selection.threshold == 0.40
    assert selection.metrics.f1 == 1.0
    assert selection.metrics.false_positive_rate == 0.0


def test_threshold_tie_break_prefers_lower_false_positive_rate():
    values = [0.1, 0.2, 0.3]
    labels = [
        ChangeClass.BENIGN_MAINTENANCE,
        ChangeClass.MALICIOUS_DRIFT,
        ChangeClass.BENIGN_MAINTENANCE,
    ]

    selection = tune_binary_threshold(
        values,
        labels,
        positive_labels=(ChangeClass.MALICIOUS_DRIFT,),
        objective="accuracy",
    )

    assert selection.metrics.false_positive_rate == 0.0
    assert selection.threshold > 0.3


def test_threshold_selection_can_optimize_malicious_only_view():
    values = [0.1, 0.4, 0.6]
    labels = [
        ChangeClass.BENIGN_MAINTENANCE,
        ChangeClass.CAPABILITY_EXPANSION,
        ChangeClass.MALICIOUS_DRIFT,
    ]

    selection = tune_binary_threshold(
        values,
        labels,
        positive_labels=(ChangeClass.MALICIOUS_DRIFT,),
    )

    assert selection.threshold == 0.6
    assert selection.metrics.precision == 1.0
    assert selection.metrics.recall == 1.0
