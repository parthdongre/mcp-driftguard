from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .graph import analyze_tool_graph, diff_tool_graph, graph_rule_baseline


class GraphEvolutionSample(BaseModel):
    sample_id: str
    family: str
    risky: bool
    old_tools: list[dict[str, Any]]
    new_tools: list[dict[str, Any]]


class GraphPrediction(BaseModel):
    sample_id: str
    family: str
    expected_risky: bool
    predicted_risky: bool
    risk_score: float = Field(ge=0.0, le=100.0)
    correct: bool


class GraphEvaluationReport(BaseModel):
    total: int = Field(ge=0)
    correct: int = Field(ge=0)
    accuracy: float = Field(ge=0.0, le=1.0)
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    f1: float = Field(ge=0.0, le=1.0)
    true_positive: int = Field(ge=0)
    false_positive: int = Field(ge=0)
    true_negative: int = Field(ge=0)
    false_negative: int = Field(ge=0)
    predictions: list[GraphPrediction] = Field(default_factory=list)


def load_graph_jsonl(path: str | Path) -> list[GraphEvolutionSample]:
    samples: list[GraphEvolutionSample] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                samples.append(GraphEvolutionSample.model_validate_json(line))
            except ValueError as exc:
                raise ValueError(
                    f"Invalid graph benchmark record on line {line_number}: {exc}"
                ) from exc
    return samples


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def evaluate_graph_samples(samples: list[GraphEvolutionSample]) -> GraphEvaluationReport:
    predictions: list[GraphPrediction] = []
    tp = fp = tn = fn = 0

    for sample in samples:
        old_graph = analyze_tool_graph(sample.old_tools)
        new_graph = analyze_tool_graph(sample.new_tools)
        assessment = graph_rule_baseline(diff_tool_graph(old_graph, new_graph))
        predicted = assessment.suspicious

        if sample.risky and predicted:
            tp += 1
        elif sample.risky and not predicted:
            fn += 1
        elif not sample.risky and predicted:
            fp += 1
        else:
            tn += 1

        predictions.append(
            GraphPrediction(
                sample_id=sample.sample_id,
                family=sample.family,
                expected_risky=sample.risky,
                predicted_risky=predicted,
                risk_score=assessment.risk_score,
                correct=predicted == sample.risky,
            )
        )

    total = len(samples)
    correct = tp + tn
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    f1 = _ratio(2 * precision * recall, precision + recall)

    return GraphEvaluationReport(
        total=total,
        correct=correct,
        accuracy=round(_ratio(correct, total), 4),
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        true_positive=tp,
        false_positive=fp,
        true_negative=tn,
        false_negative=fn,
        predictions=predictions,
    )


def evaluate_graph_file(path: str | Path) -> GraphEvaluationReport:
    return evaluate_graph_samples(load_graph_jsonl(path))
