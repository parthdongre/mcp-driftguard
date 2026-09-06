from __future__ import annotations

from driftguard.paper_readiness import PaperExperimentEvidence, assess_paper_readiness


def test_development_result_is_not_paper_eligible() -> None:
    assessment = assess_paper_readiness(PaperExperimentEvidence())
    assert not assessment.eligible
    assert "Git commit SHA" in assessment.missing
    assert "independent external attack source" in assessment.missing


def test_reused_development_test_is_disqualifying() -> None:
    evidence = PaperExperimentEvidence(
        frozen_git_commit="abc123",
        frozen_data_manifest=True,
        frozen_annotation_hash="labels-sha256",
        frozen_split_manifest=True,
        repository_disjoint_test=True,
        held_out_attack_family_test=True,
        independent_external_attack_source=True,
        real_benign_history_in_test=True,
        validation_only_threshold_selection=True,
        confidence_intervals_reported=True,
        repeated_seed_results=True,
        raw_predictions_archived=True,
        environment_archived=True,
        development_test_reused_for_feature_engineering=True,
    )
    assessment = assess_paper_readiness(evidence)
    assert not assessment.eligible
    assert assessment.disqualifiers


def test_complete_independent_experiment_can_be_claim_eligible() -> None:
    evidence = PaperExperimentEvidence(
        frozen_git_commit="abc123",
        frozen_data_manifest=True,
        frozen_annotation_hash="labels-sha256",
        frozen_split_manifest=True,
        repository_disjoint_test=True,
        held_out_attack_family_test=True,
        independent_external_attack_source=True,
        real_benign_history_in_test=True,
        validation_only_threshold_selection=True,
        confidence_intervals_reported=True,
        repeated_seed_results=True,
        raw_predictions_archived=True,
        environment_archived=True,
    )
    assessment = assess_paper_readiness(evidence)
    assert assessment.eligible
    assert not assessment.missing
    assert not assessment.disqualifiers
