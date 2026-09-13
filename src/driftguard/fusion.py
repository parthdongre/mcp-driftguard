from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from .baselines import rule_baseline
from .canonicalize import make_snapshot
from .diff import build_delta
from .graph import analyze_tool_graph, diff_tool_graph, graph_rule_baseline
from .models import ChangeClass, RiskAssessment, ToolDelta
from .runtime.temporal import DriftBudget

Detector = Callable[[ToolDelta], RiskAssessment]


class FusionScenario(BaseModel):
    """Multi-revision scenario used to measure complementary detector layers."""

    sample_id: str
    family: str
    intervention_required: bool
    tracked_tool: str
    versions: list[list[dict[str, Any]]] = Field(min_length=2)


class FusionPrediction(BaseModel):
    sample_id: str
    family: str
    expected_intervention: bool
    pairwise: bool
    temporal: bool
    graph: bool
    pairwise_temporal: bool
    pairwise_graph: bool
    full_fusion: bool
    pairwise_risk_score: float = Field(ge=0.0, le=100.0)
    temporal_cumulative_score: float = Field(ge=0.0)
    graph_risk_score: float = Field(ge=0.0, le=100.0)


class BinaryMetrics(BaseModel):
    true_positive: int = Field(ge=0)
    false_positive: int = Field(ge=0)
    true_negative: int = Field(ge=0)
    false_negative: int = Field(ge=0)
    accuracy: float = Field(ge=0.0, le=1.0)
    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    f1: float = Field(ge=0.0, le=1.0)


class FusionEvaluationReport(BaseModel):
    total: int = Field(ge=0)
    temporal_budget: float = Field(gt=0.0)
    metrics: dict[str, BinaryMetrics]
    predictions: list[FusionPrediction] = Field(default_factory=list)


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _metrics(expected: list[bool], predicted: list[bool]) -> BinaryMetrics:
    tp = fp = tn = fn = 0
    for truth, guess in zip(expected, predicted, strict=True):
        if truth and guess:
            tp += 1
        elif truth and not guess:
            fn += 1
        elif not truth and guess:
            fp += 1
        else:
            tn += 1

    total = len(expected)
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    f1 = _ratio(2 * precision * recall, precision + recall)
    return BinaryMetrics(
        true_positive=tp,
        false_positive=fp,
        true_negative=tn,
        false_negative=fn,
        accuracy=round(_ratio(tp + tn, total), 4),
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
    )


def _unique_tool(surface: list[dict[str, Any]], name: str) -> dict[str, Any]:
    matches = [tool for tool in surface if tool.get("name") == name]
    if len(matches) != 1:
        raise ValueError(
            f"Fusion scenario requires exactly one tracked tool {name!r} in every version."
        )
    return matches[0]


def evaluate_fusion_samples(
    samples: list[FusionScenario],
    *,
    detector: Detector = rule_baseline,
    temporal_budget: float = 20.0,
    temporal_window_size: int = 5,
) -> FusionEvaluationReport:
    """Evaluate detector ablations under a common binary intervention objective.

    A pairwise intervention is C2/C3 or detector abstention. Temporal and graph
    interventions are evaluated independently, then combined with logical OR.
    """

    budget = DriftBudget(
        window_size=temporal_window_size,
        budget=temporal_budget,
    )
    predictions: list[FusionPrediction] = []

    for sample in samples:
        snapshots = [
            make_snapshot(
                server_id=f"fusion:{sample.sample_id}",
                tool=_unique_tool(surface, sample.tracked_tool),
            )
            for surface in sample.versions
        ]

        pair_assessment = detector(build_delta(snapshots[-2], snapshots[-1]))
        pairwise = (
            pair_assessment.abstained
            or pair_assessment.change_class
            in {
                ChangeClass.CAPABILITY_EXPANSION,
                ChangeClass.MALICIOUS_DRIFT,
            }
        )

        temporal_evidence = budget.evaluate(snapshots, detector)
        temporal = temporal_evidence.exceeded

        old_graph = analyze_tool_graph(sample.versions[-2])
        new_graph = analyze_tool_graph(sample.versions[-1])
        graph_assessment = graph_rule_baseline(diff_tool_graph(old_graph, new_graph))
        graph = graph_assessment.suspicious

        predictions.append(
            FusionPrediction(
                sample_id=sample.sample_id,
                family=sample.family,
                expected_intervention=sample.intervention_required,
                pairwise=pairwise,
                temporal=temporal,
                graph=graph,
                pairwise_temporal=pairwise or temporal,
                pairwise_graph=pairwise or graph,
                full_fusion=pairwise or temporal or graph,
                pairwise_risk_score=pair_assessment.risk_score,
                temporal_cumulative_score=temporal_evidence.cumulative_score,
                graph_risk_score=graph_assessment.risk_score,
            )
        )

    expected = [item.expected_intervention for item in predictions]
    configurations = {
        "pairwise": [item.pairwise for item in predictions],
        "temporal": [item.temporal for item in predictions],
        "graph": [item.graph for item in predictions],
        "pairwise_temporal": [item.pairwise_temporal for item in predictions],
        "pairwise_graph": [item.pairwise_graph for item in predictions],
        "full_fusion": [item.full_fusion for item in predictions],
    }

    return FusionEvaluationReport(
        total=len(samples),
        temporal_budget=temporal_budget,
        metrics={
            name: _metrics(expected, values)
            for name, values in configurations.items()
        },
        predictions=predictions,
    )
