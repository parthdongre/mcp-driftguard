from driftguard.models import ChangeClass
from driftguard.poisoning import PoisoningDetector, poisoning_security_features
from driftguard.poisoning_benchmark import build_development_poisoning_benchmark
from driftguard.splits import apply_split_manifest, build_split_manifest


def test_security_features_separate_sensitive_existing_state_from_new_exfiltration():
    records = build_development_poisoning_benchmark(repositories=10, seed=7)
    legitimate_auth = next(
        record for record in records if "negative:legitimate_auth" in record.record_id
    )
    secret_exfil = next(
        record for record in records if record.attack_family == "secret_exfiltration"
    )

    benign_features = poisoning_security_features(legitimate_auth)
    malicious_features = poisoning_security_features(secret_exfil)

    assert benign_features["interaction__external_x_secrets"] == 0.0
    assert malicious_features["security__sensitive_required_added"] >= 1.0
    assert malicious_features["interaction__external_x_secrets"] >= 1.0


def test_detector_fits_repository_disjoint_benchmark_and_scores_poisoning_higher():
    records = build_development_poisoning_benchmark(repositories=20, seed=11)
    manifest = build_split_manifest(records, seed=11)
    split = apply_split_manifest(records, manifest)
    detector = PoisoningDetector().fit(split.train)

    benign = next(
        record
        for record in split.test
        if record.label in {
            ChangeClass.NO_MEANINGFUL_CHANGE,
            ChangeClass.BENIGN_MAINTENANCE,
            ChangeClass.CAPABILITY_EXPANSION,
        }
    )
    malicious = next(
        record for record in split.test if record.label is ChangeClass.MALICIOUS_DRIFT
    )
    benign_score = detector.predict_proba([benign])[0]
    malicious_score = detector.predict_proba([malicious])[0]

    assert 0.0 <= benign_score <= 1.0
    assert 0.0 <= malicious_score <= 1.0
    assert malicious_score > benign_score


def test_unicode_concealment_adds_format_control_feature():
    records = build_development_poisoning_benchmark(repositories=10, seed=3)
    hidden = next(record for record in records if record.attack_family == "unicode_concealment")
    features = poisoning_security_features(hidden)

    assert features["security__new_unicode_format_controls"] >= 2.0
    assert features["security__new_unicode_bidi_controls"] >= 2.0
