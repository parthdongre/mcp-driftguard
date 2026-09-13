from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .canonicalize import make_snapshot
from .diff import build_delta
from .evaluation import EvaluationSample
from .features import PAIR_FEATURE_NAMES, pair_feature_vector
from .models import ChangeClass, RiskAssessment, ToolDelta

FeatureExtractor = Callable[[ToolDelta], list[float]]

_CLASS_SEVERITY = {
    ChangeClass.NO_MEANINGFUL_CHANGE: 0.0,
    ChangeClass.BENIGN_MAINTENANCE: 25.0,
    ChangeClass.CAPABILITY_EXPANSION: 65.0,
    ChangeClass.MALICIOUS_DRIFT: 100.0,
}

_CLASS_ACTION = {
    ChangeClass.NO_MEANINGFUL_CHANGE: "allow",
    ChangeClass.BENIGN_MAINTENANCE: "allow_and_log",
    ChangeClass.CAPABILITY_EXPANSION: "require_reconsent",
    ChangeClass.MALICIOUS_DRIFT: "quarantine",
}


def _sklearn_components() -> tuple[Any, Any, Any]:
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        raise RuntimeError(
            'Classical ML support is optional. Install with: pip install -e ".[ml]"'
        ) from exc
    return LogisticRegression, make_pipeline, StandardScaler


class PairwiseLogisticDetector:
    """Lightweight learned classifier over configurable pairwise drift features."""

    def __init__(
        self,
        *,
        confidence_threshold: float = 0.55,
        margin_threshold: float = 0.10,
        feature_extractor: FeatureExtractor = pair_feature_vector,
        feature_names: tuple[str, ...] = PAIR_FEATURE_NAMES,
    ) -> None:
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be between 0 and 1")
        if not 0.0 <= margin_threshold <= 1.0:
            raise ValueError("margin_threshold must be between 0 and 1")
        if not feature_names:
            raise ValueError("feature_names cannot be empty")

        self.confidence_threshold = confidence_threshold
        self.margin_threshold = margin_threshold
        self.feature_extractor = feature_extractor
        self.feature_names = feature_names
        self._model: Any | None = None

    def _vector(self, delta: ToolDelta) -> list[float]:
        vector = self.feature_extractor(delta)
        if len(vector) != len(self.feature_names):
            raise ValueError(
                "Feature extractor returned "
                f"{len(vector)} values for {len(self.feature_names)} feature names"
            )
        return vector

    def fit(self, samples: list[EvaluationSample]) -> PairwiseLogisticDetector:
        """Fit from labeled old/new pairs. All four semantic classes should be represented."""

        if not samples:
            raise ValueError("At least one labeled sample is required")

        logistic_regression, make_pipeline, standard_scaler = _sklearn_components()
        x: list[list[float]] = []
        y: list[str] = []

        for sample in samples:
            old = make_snapshot(
                server_id=f"train:{sample.sample_id}",
                tool=sample.old_tool,
                approval_state="approved",
            )
            new = make_snapshot(
                server_id=f"train:{sample.sample_id}",
                tool=sample.new_tool,
            )
            x.append(self._vector(build_delta(old, new)))
            y.append(sample.label.value)

        if len(set(y)) < 2:
            raise ValueError("Training requires at least two semantic classes")

        self._model = make_pipeline(
            standard_scaler(),
            logistic_regression(
                class_weight="balanced",
                max_iter=2000,
                random_state=0,
            ),
        )
        self._model.fit(x, y)
        return self

    def __call__(self, delta: ToolDelta) -> RiskAssessment:
        if delta.old.sha256 == delta.new.sha256:
            return RiskAssessment(
                change_class=ChangeClass.NO_MEANINGFUL_CHANGE,
                risk_score=0.0,
                reasons=["Canonical tool definition is unchanged."],
                recommended_action="allow",
                probabilities={ChangeClass.NO_MEANINGFUL_CHANGE.value: 1.0},
                confidence=1.0,
            )

        if self._model is None:
            raise RuntimeError("PairwiseLogisticDetector must be fitted before inference")

        vector = self._vector(delta)
        probabilities = self._model.predict_proba([vector])[0]
        class_names = list(self._model.classes_)
        probability_map = {
            class_name: float(probability)
            for class_name, probability in zip(class_names, probabilities, strict=True)
        }

        ranked = sorted(probability_map.items(), key=lambda item: item[1], reverse=True)
        predicted = ChangeClass(ranked[0][0])
        confidence = ranked[0][1]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = confidence - runner_up

        abstained = confidence < self.confidence_threshold or margin < self.margin_threshold
        uncertainty_reason = None
        if abstained:
            uncertainty_reason = (
                f"Learned detector abstained: confidence={confidence:.3f}, "
                f"top-two margin={margin:.3f}."
            )

        risk_score = sum(
            probability * _CLASS_SEVERITY[ChangeClass(class_name)]
            for class_name, probability in probability_map.items()
        )

        feature_map = dict(zip(self.feature_names, vector, strict=True))
        active_features = sorted(
            (name for name, value in feature_map.items() if value > 0),
            key=lambda name: feature_map[name],
            reverse=True,
        )[:5]

        reasons = [
            (
                f"Pairwise logistic detector predicted {predicted.value} "
                f"with confidence {confidence:.3f}."
            )
        ]
        if active_features:
            reasons.append("Active pair features: " + ", ".join(active_features))
        if uncertainty_reason:
            reasons.append(uncertainty_reason)

        return RiskAssessment(
            change_class=predicted,
            risk_score=round(min(100.0, risk_score), 2),
            reasons=reasons,
            recommended_action="require_reconsent" if abstained else _CLASS_ACTION[predicted],
            probabilities={key: round(value, 6) for key, value in probability_map.items()},
            confidence=round(confidence, 6),
            abstained=abstained,
            uncertainty_reason=uncertainty_reason,
        )
