from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, Field

from ..diff import build_delta
from ..models import ChangeClass, RiskAssessment, ToolDelta, ToolSnapshot

Detector = Callable[[ToolDelta], RiskAssessment]


class TemporalStep(BaseModel):
    """One consecutive version transition included in the rolling drift budget."""

    old_sha256: str
    new_sha256: str
    risk_score: float = Field(ge=0.0, le=100.0)
    change_class: ChangeClass


class DriftBudgetEvidence(BaseModel):
    """Rolling evidence used to catch cumulative low-and-slow semantic drift."""

    window_size: int = Field(ge=1)
    comparisons: int = Field(ge=0)
    cumulative_score: float = Field(ge=0.0)
    budget: float = Field(gt=0.0)
    exceeded: bool
    steps: list[TemporalStep] = Field(default_factory=list)


class DriftBudget:
    """Accumulate risk across consecutive observed versions within a rolling window."""

    def __init__(self, *, window_size: int = 5, budget: float = 100.0) -> None:
        if window_size < 1:
            raise ValueError("window_size must be at least 1")
        if budget <= 0:
            raise ValueError("budget must be greater than 0")
        self.window_size = window_size
        self.budget = float(budget)

    def evaluate(
        self,
        history: list[ToolSnapshot],
        detector: Detector,
    ) -> DriftBudgetEvidence:
        relevant = history[-(self.window_size + 1) :]
        steps: list[TemporalStep] = []

        for index in range(len(relevant) - 1):
            old = relevant[index]
            new = relevant[index + 1]
            assessment = detector(build_delta(old, new))
            steps.append(
                TemporalStep(
                    old_sha256=old.sha256,
                    new_sha256=new.sha256,
                    risk_score=assessment.risk_score,
                    change_class=assessment.change_class,
                )
            )

        cumulative_score = round(sum(step.risk_score for step in steps), 2)
        return DriftBudgetEvidence(
            window_size=self.window_size,
            comparisons=len(steps),
            cumulative_score=cumulative_score,
            budget=self.budget,
            exceeded=cumulative_score > self.budget,
            steps=steps,
        )
