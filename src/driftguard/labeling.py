from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .models import ChangeClass


class EvidenceTag(StrEnum):
    """Annotation tags used to explain why a version transition received a label."""

    FORMATTING_ONLY = "formatting_only"
    SEMANTIC_EQUIVALENCE = "semantic_equivalence"
    DOCUMENTATION_CLARIFICATION = "documentation_clarification"
    BUG_FIX = "bug_fix"
    OPTIONAL_NON_SENSITIVE_PARAMETER = "optional_non_sensitive_parameter"
    CONSTRAINT_NARROWING = "constraint_narrowing"
    NEW_CAPABILITY = "new_capability"
    BROADER_SCOPE = "broader_scope"
    NEW_SENSITIVE_PARAMETER = "new_sensitive_parameter"
    NEW_EXTERNAL_DESTINATION = "new_external_destination"
    NEW_DESTRUCTIVE_EFFECT = "new_destructive_effect"
    NEW_EXECUTION_EFFECT = "new_execution_effect"
    CREDENTIAL_ACCESS = "credential_access"
    DATA_DISCLOSURE = "data_disclosure"
    HIDDEN_INSTRUCTION = "hidden_instruction"
    CROSS_TOOL_STEERING = "cross_tool_steering"
    POLICY_OVERRIDE = "policy_override"
    MALICIOUS_DEFAULT = "malicious_default"
    UNCERTAIN_INTENT = "uncertain_intent"


@dataclass(frozen=True)
class LabelDecision:
    """Human annotation decision for one old/new tool-definition transition."""

    label: ChangeClass
    evidence: tuple[EvidenceTag, ...]
    rationale: str
    requires_second_review: bool = False


def recommended_label(
    evidence: Iterable[EvidenceTag],
    *,
    known_legitimate_change: bool | None = None,
) -> LabelDecision:
    """Return a conservative annotation recommendation from explicit evidence tags.

    This helper is for annotation consistency, not automatic ground-truth generation.
    Human annotators remain responsible for checking the actual old/new definitions
    and project context. In particular, intent cannot be inferred from schema text alone.
    """

    tags = set(evidence)
    if not tags:
        return LabelDecision(
            label=ChangeClass.NO_MEANINGFUL_CHANGE,
            evidence=(),
            rationale="No security- or meaning-relevant change was recorded.",
            requires_second_review=True,
        )

    malicious_tags = {
        EvidenceTag.HIDDEN_INSTRUCTION,
        EvidenceTag.CROSS_TOOL_STEERING,
        EvidenceTag.POLICY_OVERRIDE,
        EvidenceTag.MALICIOUS_DEFAULT,
    }
    high_risk_capability_tags = {
        EvidenceTag.CREDENTIAL_ACCESS,
        EvidenceTag.DATA_DISCLOSURE,
        EvidenceTag.NEW_DESTRUCTIVE_EFFECT,
        EvidenceTag.NEW_EXECUTION_EFFECT,
    }
    capability_tags = {
        EvidenceTag.NEW_CAPABILITY,
        EvidenceTag.BROADER_SCOPE,
        EvidenceTag.NEW_SENSITIVE_PARAMETER,
        EvidenceTag.NEW_EXTERNAL_DESTINATION,
        *high_risk_capability_tags,
    }
    benign_tags = {
        EvidenceTag.DOCUMENTATION_CLARIFICATION,
        EvidenceTag.BUG_FIX,
        EvidenceTag.OPTIONAL_NON_SENSITIVE_PARAMETER,
        EvidenceTag.CONSTRAINT_NARROWING,
    }
    equivalent_tags = {
        EvidenceTag.FORMATTING_ONLY,
        EvidenceTag.SEMANTIC_EQUIVALENCE,
    }

    if tags & malicious_tags:
        return LabelDecision(
            label=ChangeClass.MALICIOUS_DRIFT,
            evidence=tuple(sorted(tags, key=str)),
            rationale="Transition contains explicit poisoning/steering/override evidence.",
            requires_second_review=True,
        )

    if tags & capability_tags:
        if known_legitimate_change is False:
            return LabelDecision(
                label=ChangeClass.MALICIOUS_DRIFT,
                evidence=tuple(sorted(tags, key=str)),
                rationale="Security-significant capability expansion is known to be unauthorized.",
                requires_second_review=True,
            )
        return LabelDecision(
            label=ChangeClass.CAPABILITY_EXPANSION,
            evidence=tuple(sorted(tags, key=str)),
            rationale=(
                "Transition expands effective capability or scope and should cross the "
                "re-consent boundary unless independent evidence establishes malicious intent."
            ),
            requires_second_review=known_legitimate_change is None or bool(tags & high_risk_capability_tags),
        )

    if tags <= equivalent_tags:
        return LabelDecision(
            label=ChangeClass.NO_MEANINGFUL_CHANGE,
            evidence=tuple(sorted(tags, key=str)),
            rationale="Only formatting or semantically equivalent restatement was observed.",
        )

    if tags & benign_tags:
        return LabelDecision(
            label=ChangeClass.BENIGN_MAINTENANCE,
            evidence=tuple(sorted(tags, key=str)),
            rationale="Meaningful maintenance change without a newly implied sensitive capability.",
        )

    return LabelDecision(
        label=ChangeClass.BENIGN_MAINTENANCE,
        evidence=tuple(sorted(tags, key=str)),
        rationale="Evidence does not establish a consent-boundary or malicious transition.",
        requires_second_review=EvidenceTag.UNCERTAIN_INTENT in tags,
    )


def inter_annotator_agreement(labels_a: Iterable[ChangeClass], labels_b: Iterable[ChangeClass]) -> float:
    """Return raw agreement for two aligned annotation sequences.

    Cohen's kappa is computed in the experiment layer when scikit-learn is available;
    this dependency-free statistic is useful during data collection.
    """

    left = list(labels_a)
    right = list(labels_b)
    if len(left) != len(right):
        raise ValueError("Annotation sequences must have equal length")
    if not left:
        return 0.0
    return sum(a == b for a, b in zip(left, right, strict=True)) / len(left)
