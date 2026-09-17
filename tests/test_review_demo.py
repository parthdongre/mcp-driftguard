from driftguard.review_demo import render_midsem_report, run_midsem_review_demo


def test_midsem_demo_detects_accumulated_low_and_slow_drift():
    steps = run_midsem_review_demo()

    assert len(steps) == 4
    assert steps[0].alerted is False
    assert any(step.alerted for step in steps[1:])
    assert steps[-1].action == "QUARANTINE"
    assert steps[-1].baseline_risk >= steps[0].baseline_risk


def test_midsem_report_explains_baseline_and_policy_action():
    report = render_midsem_report(run_midsem_review_demo())

    assert "approved baseline" in report.lower()
    assert "QUARANTINE" in report
    assert "CUSUM" in report
