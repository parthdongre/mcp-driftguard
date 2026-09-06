from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from statistics import mean

from .canonicalize import make_snapshot
from .dataset import TrajectoryDatasetRecord
from .models import ChangeClass
from .temporal import SequentialDriftMonitor, TemporalConfig


@dataclass(frozen=True)
class TrajectoryRun:
    trajectory_id: str
    positive_onset_step: int | None
    first_alert_step: int | None
    first_post_onset_alert_step: int | None
    detection_delay: int | None
    false_alarm: bool
    detected: bool


@dataclass(frozen=True)
class TrajectoryMetrics:
    trajectories: int
    positive_trajectories: int
    benign_trajectories: int
    detected_positive_trajectories: int
    detection_rate: float
    false_alarm_trajectories: int
    false_alarm_rate: float
    average_detection_delay: float | None


def _positive_onset(
    trajectory: TrajectoryDatasetRecord,
    positive_labels: set[ChangeClass],
) -> int | None:
    for step_index, step in enumerate(trajectory.steps[1:], start=1):
        if step.transition_label in positive_labels:
            return step_index
    return None


def evaluate_trajectory(
    trajectory: TrajectoryDatasetRecord,
    *,
    config: TemporalConfig | None = None,
    positive_labels: tuple[ChangeClass, ...] = (
        ChangeClass.CAPABILITY_EXPANSION,
        ChangeClass.MALICIOUS_DRIFT,
    ),
) -> TrajectoryRun:
    """Run the current sequential baseline over one labeled version trajectory.

    Step indices are version indices: the approved baseline is step 0, and step 1 is
    the first transition after approval. Detection delay is measured from the first
    transition whose label belongs to ``positive_labels``.
    """

    if len(trajectory.steps) < 2:
        raise ValueError("A trajectory requires at least two versions")

    positive_set = set(positive_labels)
    onset = _positive_onset(trajectory, positive_set)
    approved = make_snapshot(
        server_id=trajectory.server_id,
        tool=trajectory.steps[0].tool,
        approval_state="approved",
    )
    monitor = SequentialDriftMonitor(approved, config=config)

    alert_steps: list[int] = []
    for step_index, step in enumerate(trajectory.steps[1:], start=1):
        current = make_snapshot(server_id=trajectory.server_id, tool=step.tool)
        assessment = monitor.observe(current)
        if assessment.alerted:
            alert_steps.append(step_index)

    first_alert = alert_steps[0] if alert_steps else None
    first_post_onset: int | None = None
    if onset is not None:
        first_post_onset = next((step for step in alert_steps if step >= onset), None)

    false_alarm = bool(alert_steps) if onset is None else any(step < onset for step in alert_steps)
    detected = onset is not None and first_post_onset is not None
    delay = first_post_onset - onset if detected and first_post_onset is not None else None

    return TrajectoryRun(
        trajectory_id=trajectory.trajectory_id,
        positive_onset_step=onset,
        first_alert_step=first_alert,
        first_post_onset_alert_step=first_post_onset,
        detection_delay=delay,
        false_alarm=false_alarm,
        detected=detected,
    )


def aggregate_trajectory_metrics(runs: Iterable[TrajectoryRun]) -> TrajectoryMetrics:
    runs = list(runs)
    if not runs:
        raise ValueError("At least one trajectory run is required")

    positive = [run for run in runs if run.positive_onset_step is not None]
    benign = [run for run in runs if run.positive_onset_step is None]
    detected = [run for run in positive if run.detected]
    false_alarms = [run for run in runs if run.false_alarm]
    delays = [run.detection_delay for run in detected if run.detection_delay is not None]

    detection_rate = len(detected) / len(positive) if positive else 0.0
    false_alarm_rate = len(false_alarms) / len(runs) if runs else 0.0
    return TrajectoryMetrics(
        trajectories=len(runs),
        positive_trajectories=len(positive),
        benign_trajectories=len(benign),
        detected_positive_trajectories=len(detected),
        detection_rate=round(detection_rate, 6),
        false_alarm_trajectories=len(false_alarms),
        false_alarm_rate=round(false_alarm_rate, 6),
        average_detection_delay=round(mean(delays), 6) if delays else None,
    )


def evaluate_trajectories(
    trajectories: Iterable[TrajectoryDatasetRecord],
    *,
    config: TemporalConfig | None = None,
    positive_labels: tuple[ChangeClass, ...] = (
        ChangeClass.CAPABILITY_EXPANSION,
        ChangeClass.MALICIOUS_DRIFT,
    ),
) -> tuple[list[TrajectoryRun], TrajectoryMetrics]:
    runs = [
        evaluate_trajectory(
            trajectory,
            config=config,
            positive_labels=positive_labels,
        )
        for trajectory in trajectories
    ]
    return runs, aggregate_trajectory_metrics(runs)
