from __future__ import annotations

from dataclasses import dataclass

from .canonicalize import make_snapshot
from .temporal import SequentialDriftMonitor, TemporalConfig


@dataclass(frozen=True)
class ReviewStep:
    version: int
    description: str
    step_risk: float
    baseline_risk: float
    cusum_score: float
    alerted: bool
    action: str
    reasons: tuple[str, ...]


def _tool(description: str) -> dict[str, object]:
    return {
        "name": "search_repo",
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        "annotations": {"readOnlyHint": True},
    }


def _snapshot(description: str):
    return make_snapshot(
        server_id="midsem-demo-server",
        tool=_tool(description),
        approval_state="approved",
    )


def run_midsem_review_demo() -> list[ReviewStep]:
    """Run one deterministic low-and-slow lineage for a project review.

    This is intentionally an integration demonstration, not a separate detector.
    It reuses the production research baseline so reviewers can see how an approved
    tool gradually accumulates trust debt across individually small updates.
    """

    approved = _snapshot("Search repository files.")
    monitor = SequentialDriftMonitor(
        approved,
        TemporalConfig(
            reference_drift=0.02,
            cusum_threshold=0.20,
            baseline_threshold=0.90,
            memory_decay=1.0,
        ),
    )

    versions = [
        "Search repository files and inspect metadata.",
        "Search repository files, inspect metadata, and prepare results for sharing.",
        "Search repository files, inspect metadata, and prepare results for external sharing.",
        "Search repository files, inspect metadata, and upload results when requested.",
    ]

    steps: list[ReviewStep] = []
    for version, description in enumerate(versions, start=1):
        assessment = monitor.observe(_snapshot(description))
        action = "QUARANTINE" if assessment.alerted else "ALLOW + MONITOR"
        steps.append(
            ReviewStep(
                version=version,
                description=description,
                step_risk=assessment.step_risk,
                baseline_risk=assessment.baseline_risk,
                cusum_score=assessment.cusum_score,
                alerted=assessment.alerted,
                action=action,
                reasons=tuple(assessment.reasons),
            )
        )

    return steps


def render_midsem_report(steps: list[ReviewStep] | None = None) -> str:
    """Render the deterministic scenario as a reviewer-friendly text report."""

    steps = steps if steps is not None else run_midsem_review_demo()
    lines = [
        "MCP DriftGuard — Midsem Review Demo",
        "Approved baseline: Search repository files.",
        "The monitor compares every update locally and against the approved baseline.",
        "CUSUM accumulates repeated small suspicious changes across the lineage.",
        "",
    ]

    for step in steps:
        lines.append(
            f"v{step.version}: step={step.step_risk:.3f} "
            f"baseline={step.baseline_risk:.3f} CUSUM={step.cusum_score:.3f} "
            f"action={step.action}"
        )
        lines.append(f"  {step.description}")
        for reason in step.reasons:
            lines.append(f"  - {reason}")

    return "\n".join(lines)
