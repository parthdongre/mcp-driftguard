from driftguard.models import ChangeClass
from driftguard.thresholds import tune_binary_threshold, tune_margin_threshold


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


def test_margin_threshold_uses_midpoint_of_validation_separation_gap():
    values = [0.01, 0.04, 0.88, 0.96]
    labels = [
        ChangeClass.BENIGN_MAINTENANCE,
        ChangeClass.CAPABILITY_EXPANSION,
        ChangeClass.MALICIOUS_DRIFT,
        ChangeClass.MALICIOUS_DRIFT,
    ]

    selection = tune_margin_threshold(values, labels)

    assert selection.objective == "validation_margin"
    assert selection.threshold == 0.46
    assert selection.objective_value == 0.84
    assert selection.metrics.accuracy == 1.0


def test_margin_threshold_falls_back_when_validation_classes_overlap():
    values = [0.1, 0.7, 0.4, 0.8]
    labels = [
        ChangeClass.BENIGN_MAINTENANCE,
        ChangeClass.BENIGN_MAINTENANCE,
        ChangeClass.MALICIOUS_DRIFT,
        ChangeClass.MALICIOUS_DRIFT,
    ]

    selection = tune_margin_threshold(values, labels)

    assert selection.objective == "f1"
    assert 0.0 <= selection.threshold <= 0.8
