from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PaperExperimentEvidence:
    """Evidence required before a metric can be promoted from development to paper claim."""

    frozen_git_commit: str | None = None
    frozen_data_manifest: bool = False
    frozen_annotation_hash: str | None = None
    frozen_split_manifest: bool = False
    repository_disjoint_test: bool = False
    held_out_attack_family_test: bool = False
    independent_external_attack_source: bool = False
    real_benign_history_in_test: bool = False
    validation_only_threshold_selection: bool = False
    confidence_intervals_reported: bool = False
    repeated_seed_results: bool = False
    raw_predictions_archived: bool = False
    environment_archived: bool = False
    development_test_reused_for_feature_engineering: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PaperReadinessAssessment:
    eligible: bool
    passed: tuple[str, ...]
    missing: tuple[str, ...]
    disqualifiers: tuple[str, ...]


_REQUIRED_BOOLEAN_EVIDENCE = {
    "frozen_data_manifest": "data manifest frozen",
    "frozen_split_manifest": "split manifest frozen",
    "repository_disjoint_test": "repository-disjoint test",
    "held_out_attack_family_test": "held-out attack-family test",
    "independent_external_attack_source": "independent external attack source",
    "real_benign_history_in_test": "real benign history represented in test",
    "validation_only_threshold_selection": "validation-only threshold selection",
    "confidence_intervals_reported": "confidence intervals reported",
    "repeated_seed_results": "repeated-seed learned-model results",
    "raw_predictions_archived": "raw predictions archived",
    "environment_archived": "environment archived",
}


def assess_paper_readiness(evidence: PaperExperimentEvidence) -> PaperReadinessAssessment:
    passed: list[str] = []
    missing: list[str] = []

    if evidence.frozen_git_commit:
        passed.append("Git commit frozen")
    else:
        missing.append("Git commit SHA")

    if evidence.frozen_annotation_hash:
        passed.append("annotation labels frozen")
    else:
        missing.append("frozen annotation hash")

    for field_name, description in _REQUIRED_BOOLEAN_EVIDENCE.items():
        if getattr(evidence, field_name):
            passed.append(description)
        else:
            missing.append(description)

    disqualifiers: list[str] = []
    if evidence.development_test_reused_for_feature_engineering:
        disqualifiers.append(
            "The claimed final test set was reused during feature engineering; a fresh final test is required."
        )

    return PaperReadinessAssessment(
        eligible=not missing and not disqualifiers,
        passed=tuple(passed),
        missing=tuple(missing),
        disqualifiers=tuple(disqualifiers),
    )
