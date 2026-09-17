import json

from driftguard.review_demo import (
    main,
    render_midsem_json,
    render_midsem_report,
    run_midsem_review_demo,
)


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


def test_midsem_json_is_machine_readable_and_keeps_reviewer_evidence():
    payload = json.loads(render_midsem_json(run_midsem_review_demo()))

    assert payload["project"] == "MCP DriftGuard"
    assert payload["approved_baseline"] == "Search repository files."
    assert len(payload["steps"]) == 4
    assert payload["steps"][-1]["action"] == "QUARANTINE"
    assert payload["steps"][-1]["alerted"] is True


def test_cli_json_mode_prints_the_same_evidence(capsys):
    exit_code = main(["--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["steps"][-1]["action"] == "QUARANTINE"
