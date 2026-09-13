from driftguard.evaluation import EvaluationSample, evaluate_samples, load_jsonl
from driftguard.models import ChangeClass, RiskAssessment


def _tool(description: str, expected: str):
    return {
        "name": "demo_tool",
        "description": description,
        "xExpectedClass": expected,
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    }


def _perfect_test_detector(delta):
    expected = ChangeClass(delta.new.raw_tool["xExpectedClass"])
    return RiskAssessment(
        change_class=expected,
        risk_score=0.0 if expected == ChangeClass.NO_MEANINGFUL_CHANGE else 50.0,
        recommended_action="test",
    )


def test_evaluation_metrics_for_perfect_detector():
    samples = [
        EvaluationSample(
            sample_id="c0",
            family="test",
            label=ChangeClass.NO_MEANINGFUL_CHANGE,
            old_tool=_tool("same", "C0"),
            new_tool=_tool("same", "C0"),
        ),
        EvaluationSample(
            sample_id="c1",
            family="test",
            label=ChangeClass.BENIGN_MAINTENANCE,
            old_tool=_tool("old", "C1"),
            new_tool=_tool("new", "C1"),
        ),
        EvaluationSample(
            sample_id="c2",
            family="test",
            label=ChangeClass.CAPABILITY_EXPANSION,
            old_tool=_tool("old", "C2"),
            new_tool=_tool("new", "C2"),
        ),
        EvaluationSample(
            sample_id="c3",
            family="test",
            label=ChangeClass.MALICIOUS_DRIFT,
            old_tool=_tool("old", "C3"),
            new_tool=_tool("new", "C3"),
        ),
    ]

    report = evaluate_samples(samples, detector=_perfect_test_detector)

    assert report.total == 4
    assert report.correct == 4
    assert report.accuracy == 1.0
    assert report.macro_f1 == 1.0
    assert all(metrics.f1 == 1.0 for metrics in report.per_class.values())


def test_jsonl_loader_reports_labeled_samples(tmp_path):
    path = tmp_path / "tiny.jsonl"
    path.write_text(
        EvaluationSample(
            sample_id="one",
            family="loader",
            label=ChangeClass.NO_MEANINGFUL_CHANGE,
            old_tool=_tool("same", "C0"),
            new_tool=_tool("same", "C0"),
        ).model_dump_json()
        + "\n",
        encoding="utf-8",
    )

    samples = load_jsonl(path)

    assert len(samples) == 1
    assert samples[0].sample_id == "one"
    assert samples[0].label == ChangeClass.NO_MEANINGFUL_CHANGE
