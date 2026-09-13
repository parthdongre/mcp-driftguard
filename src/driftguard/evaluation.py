from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .baselines import rule_baseline
from .canonicalize import make_snapshot
from .diff import build_delta
from .models import ChangeClass, RiskAssessment, ToolDelta

Detector = Callable[[ToolDelta], RiskAssessment]


class EvaluationSample(BaseModel):
    """One labeled old/new MCP tool pair used in reproducible experiments."""

    sample_id: str
    family: str
    label: ChangeClass
    old_tool: dict[str, Any]
    new_tool: dict[str, Any]


class SamplePrediction(BaseModel):
    sample_id: str
    family: str
    expected: ChangeClass
    predicted: ChangeClass
    risk_score: float = Field(ge=0.0, le=100.0)
    correct: bool
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    abstained: bool = False


class PerClassMetrics(BaseModel):
    support: int = Field(ge=0)
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    f1: float = Field(ge=0.0, le=1.0)


class EvaluationReport(BaseModel):
    total: int = Field(ge=0)
    correct: int = Field(ge=0)
    accuracy: float = Field(ge=0.0, le=1.0)
    macro_f1: float = Field(ge=0.0, le=1.0)
    abstentions: int = Field(ge=0)
    abstention_rate: float = Field(ge=0.0, le=1.0)
    per_class: dict[str, PerClassMetrics]
    confusion_matrix: dict[str, dict[str, int]]
    predictions: list[SamplePrediction] = Field(default_factory=list)


def load_jsonl(path: str | Path) -> list[EvaluationSample]:
    """Load a versioned JSONL benchmark without requiring pandas or sklearn."""

    samples: list[EvaluationSample] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                samples.append(EvaluationSample.model_validate_json(line))
            except ValueError as exc:
                raise ValueError(f"Invalid benchmark record on line {line_number}: {exc}") from exc
    return samples


def _safe_ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def evaluate_samples(
    samples: list[EvaluationSample],
    detector: Detector = rule_baseline,
) -> EvaluationReport:
    """Evaluate a detector against semantic labels and return inspectable metrics."""

    classes = list(ChangeClass)
    matrix = {
        actual.value: {predicted.value: 0 for predicted in classes}
        for actual in classes
    }
    predictions: list[SamplePrediction] = []
    correct = 0

    for sample in samples:
        old = make_snapshot(
            server_id=f"benchmark:{sample.sample_id}",
            tool=sample.old_tool,
            approval_state="approved",
        )
        new = make_snapshot(
            server_id=f"benchmark:{sample.sample_id}",
            tool=sample.new_tool,
        )
        assessment = detector(build_delta(old, new))
        predicted = assessment.change_class
        is_correct = predicted == sample.label

        matrix[sample.label.value][predicted.value] += 1
        correct += int(is_correct)
        predictions.append(
            SamplePrediction(
                sample_id=sample.sample_id,
                family=sample.family,
                expected=sample.label,
                predicted=predicted,
                risk_score=assessment.risk_score,
                correct=is_correct,
                confidence=assessment.confidence,
                abstained=assessment.abstained,
            )
        )

    per_class: dict[str, PerClassMetrics] = {}
    supported_f1: list[float] = []

    for current in classes:
        key = current.value
        true_positive = matrix[key][key]
        false_positive = sum(
            matrix[actual.value][key] for actual in classes if actual != current
        )
        false_negative = sum(
            matrix[key][predicted.value]
            for predicted in classes
            if predicted != current
        )
        support = sum(matrix[key].values())
        precision = _safe_ratio(true_positive, true_positive + false_positive)
        recall = _safe_ratio(true_positive, true_positive + false_negative)
        f1 = _safe_ratio(2 * precision * recall, precision + recall)

        metrics = PerClassMetrics(
            support=support,
            precision=round(precision, 4),
            recall=round(recall, 4),
            f1=round(f1, 4),
        )
        per_class[key] = metrics
        if support:
            supported_f1.append(f1)

    total = len(samples)
    abstentions = sum(int(item.abstained) for item in predictions)
    accuracy = _safe_ratio(correct, total)
    macro_f1 = sum(supported_f1) / len(supported_f1) if supported_f1 else 0.0

    return EvaluationReport(
        total=total,
        correct=correct,
        accuracy=round(accuracy, 4),
        macro_f1=round(macro_f1, 4),
        abstentions=abstentions,
        abstention_rate=round(_safe_ratio(abstentions, total), 4),
        per_class=per_class,
        confusion_matrix=matrix,
        predictions=predictions,
    )


def evaluate_file(
    path: str | Path,
    detector: Detector = rule_baseline,
) -> EvaluationReport:
    return evaluate_samples(load_jsonl(path), detector)
