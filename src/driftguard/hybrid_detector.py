from __future__ import annotations

from collections.abc import Iterable

from .dataset import PairDatasetRecord
from .models import ChangeClass, RiskAssessment
from .poisoning import PoisoningDetector, poisoning_security_features


def structural_guard_probability(record: PairDatasetRecord) -> float:
    """Return a high-confidence probability floor for deterministic security invariants.

    The learned detector is best at semantic and lexical generalization, but some tool
    definition changes are security violations by construction and should not depend on
    whether the model has seen a similar positive example. These guards deliberately use
    conjunctions so legitimate capability expansion remains a hard negative.
    """

    features = poisoning_security_features(record)

    hidden_external_sink = (
        features.get("security__external_default_added", 0.0) > 0
        and features.get("security__external_destination_parameter_added", 0.0) > 0
    )
    readonly_destructive_mismatch = (
        features.get("security__readonly_capability_contradiction", 0.0) > 0
        and features.get("interaction__readonly_x_destructive", 0.0) > 0
    )
    declared_non_destructive_but_destructive = (
        features.get("security__destructive_annotation_contradiction", 0.0) > 0
    )

    if readonly_destructive_mismatch or declared_non_destructive_but_destructive:
        return 0.995
    if hidden_external_sink:
        return 0.99
    return 0.0


class HybridPoisoningDetector:
    """Production-facing poisoning detector: learned ranking plus structural invariants."""

    def __init__(
        self,
        *,
        threshold: float = 0.5,
        class_weight: str | None = "balanced",
    ) -> None:
        self.threshold = float(threshold)
        self.learned = PoisoningDetector(
            threshold=threshold,
            class_weight=class_weight,
        )

    def fit(self, records: Iterable[PairDatasetRecord]) -> HybridPoisoningDetector:
        self.learned.fit(records)
        return self

    def predict_proba(self, records: Iterable[PairDatasetRecord]) -> list[float]:
        records = list(records)
        if not records:
            return []
        learned_probabilities = self.learned.predict_proba(records)
        probabilities: list[float] = []
        for record, learned_probability in zip(
            records,
            learned_probabilities,
            strict=True,
        ):
            guard_probability = structural_guard_probability(record)
            probabilities.append(max(float(learned_probability), guard_probability))
        return probabilities

    def predict(
        self,
        records: Iterable[PairDatasetRecord],
        *,
        threshold: float | None = None,
    ) -> list[bool]:
        cutoff = self.threshold if threshold is None else float(threshold)
        return [probability >= cutoff for probability in self.predict_proba(records)]

    def assess(
        self,
        record: PairDatasetRecord,
        *,
        threshold: float | None = None,
    ) -> RiskAssessment:
        learned_probability = self.learned.predict_proba([record])[0]
        guard_probability = structural_guard_probability(record)
        probability = max(learned_probability, guard_probability)
        cutoff = self.threshold if threshold is None else float(threshold)
        poisoned = probability >= cutoff

        reasons = [
            f"learned_poisoning_probability={learned_probability:.4f}",
        ]
        if guard_probability > 0:
            reasons.append(
                f"structural_security_invariant_probability_floor={guard_probability:.4f}"
            )

        return RiskAssessment(
            change_class=(
                ChangeClass.MALICIOUS_DRIFT if poisoned else ChangeClass.BENIGN_MAINTENANCE
            ),
            risk_score=round(100.0 * probability, 2),
            probabilities={
                "C3": round(probability, 6),
                "not_C3": round(1.0 - probability, 6),
            },
            reasons=reasons,
            recommended_action="quarantine" if poisoned else "allow_or_apply_consent_policy",
        )
