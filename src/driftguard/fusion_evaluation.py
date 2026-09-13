from __future__ import annotations

from pathlib import Path

from .fusion import FusionEvaluationReport, FusionScenario, evaluate_fusion_samples


def load_fusion_jsonl(path: str | Path) -> list[FusionScenario]:
    samples: list[FusionScenario] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                samples.append(FusionScenario.model_validate_json(line))
            except ValueError as exc:
                raise ValueError(
                    f"Invalid fusion benchmark record on line {line_number}: {exc}"
                ) from exc
    return samples


def evaluate_fusion_file(
    path: str | Path,
    *,
    temporal_budget: float = 20.0,
    temporal_window_size: int = 5,
) -> FusionEvaluationReport:
    return evaluate_fusion_samples(
        load_fusion_jsonl(path),
        temporal_budget=temporal_budget,
        temporal_window_size=temporal_window_size,
    )
