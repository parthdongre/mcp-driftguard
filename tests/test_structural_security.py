from driftguard.poisoning import poisoning_security_features
from driftguard.poisoning_benchmark import build_development_poisoning_benchmark
from driftguard.poisoning_challenges import build_structural_challenge_records


def _records():
    development = build_development_poisoning_benchmark(repositories=10, seed=101)
    return build_structural_challenge_records(development)


def test_external_default_distinguishes_hidden_sink_from_user_supplied_destination():
    records = _records()
    hidden_sink = next(
        record for record in records if record.attack_family == "redirect_sink_injection"
    )
    user_destination = next(
        record for record in records if "negative:user_destination" in record.record_id
    )

    attack_features = poisoning_security_features(hidden_sink)
    benign_features = poisoning_security_features(user_destination)

    assert attack_features["security__external_default_added"] == 1.0
    assert attack_features["security__external_destination_parameter_added"] == 1.0
    assert attack_features["interaction__external_default_x_new_destination_param"] == 1.0
    assert benign_features["security__external_default_added"] == 0.0
    assert benign_features["security__external_destination_parameter_added"] == 1.0
    assert benign_features["interaction__external_default_x_new_destination_param"] == 0.0


def test_safety_hint_contradiction_distinguishes_deception_from_declared_mutation():
    records = _records()
    mismatch = next(
        record for record in records if record.attack_family == "safety_hint_mismatch"
    )
    declared = next(
        record for record in records if "negative:declared_mutation" in record.record_id
    )

    attack_features = poisoning_security_features(mismatch)
    benign_features = poisoning_security_features(declared)

    assert attack_features["security__readonly_capability_contradiction"] == 1.0
    assert attack_features["security__destructive_annotation_contradiction"] == 1.0
    assert attack_features["interaction__readonly_x_destructive"] == 1.0
    assert benign_features["security__readonly_capability_contradiction"] == 0.0
    assert benign_features["interaction__readonly_x_destructive"] == 0.0


def test_documentation_url_does_not_look_like_an_execution_sink_default():
    documentation = next(
        record for record in _records() if "negative:documentation_url" in record.record_id
    )
    features = poisoning_security_features(documentation)

    assert features["security__external_default_added"] == 0.0
    assert features["interaction__external_default_x_new_destination_param"] == 0.0
