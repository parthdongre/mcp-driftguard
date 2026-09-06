from driftguard.mutations import build_low_and_slow_trajectory
from driftguard.temporal import TemporalConfig
from driftguard.trajectory_evaluation import (
    TrajectoryRun,
    aggregate_trajectory_metrics,
    evaluate_trajectory,
)


def tool():
    return {
        "name": "search_repo",
        "description": "Search repository files.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        "annotations": {"readOnlyHint": True},
    }


def test_trajectory_evaluator_tracks_onset_detection_and_early_alerts():
    trajectory = build_low_and_slow_trajectory(
        repository_id="owner/repo",
        server_id="server-1",
        tool=tool(),
    )
    run = evaluate_trajectory(
        trajectory,
        config=TemporalConfig(
            reference_drift=0.0,
            cusum_threshold=0.0,
            baseline_threshold=1.0,
            memory_decay=1.0,
        ),
    )

    assert run.positive_onset_step == 3
    assert run.first_alert_step == 1
    assert run.first_post_onset_alert_step == 3
    assert run.detection_delay == 0
    assert run.detected is True
    assert run.false_alarm is True


def test_aggregate_trajectory_metrics_reports_detection_delay():
    runs = [
        TrajectoryRun(
            trajectory_id="attack-1",
            positive_onset_step=2,
            first_alert_step=3,
            first_post_onset_alert_step=3,
            detection_delay=1,
            false_alarm=False,
            detected=True,
        ),
        TrajectoryRun(
            trajectory_id="attack-2",
            positive_onset_step=2,
            first_alert_step=None,
            first_post_onset_alert_step=None,
            detection_delay=None,
            false_alarm=False,
            detected=False,
        ),
        TrajectoryRun(
            trajectory_id="benign-1",
            positive_onset_step=None,
            first_alert_step=2,
            first_post_onset_alert_step=None,
            detection_delay=None,
            false_alarm=True,
            detected=False,
        ),
    ]
    metrics = aggregate_trajectory_metrics(runs)

    assert metrics.positive_trajectories == 2
    assert metrics.benign_trajectories == 1
    assert metrics.detected_positive_trajectories == 1
    assert metrics.detection_rate == 0.5
    assert metrics.false_alarm_trajectories == 1
    assert metrics.false_alarm_rate == 1 / 3
    assert metrics.average_detection_delay == 1.0
