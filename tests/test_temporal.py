from driftguard.models import ChangeClass, RiskAssessment
from driftguard.runtime import DriftBudget, DriftGuardService, EnforcementAction


def _tool(description: str):
    return {
        "name": "search_repository",
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }


def _steady_benign_detector(delta):
    if delta.old.sha256 == delta.new.sha256:
        return RiskAssessment(
            change_class=ChangeClass.NO_MEANINGFUL_CHANGE,
            risk_score=0.0,
            recommended_action="allow",
        )
    return RiskAssessment(
        change_class=ChangeClass.BENIGN_MAINTENANCE,
        risk_score=3.0,
        reasons=["Synthetic low-risk step for temporal-budget testing."],
        recommended_action="allow_and_log",
    )


def test_cumulative_drift_escalates_multiple_small_approved_changes():
    service = DriftGuardService(
        detector=_steady_benign_detector,
        drift_budget=DriftBudget(window_size=3, budget=5.0),
    )

    first = service.observe_tool(server_id="demo", tool=_tool("Search repository files."))
    service.approve(first.snapshot)

    second = service.observe_tool(
        server_id="demo",
        tool=_tool("Search repository files by keyword."),
    )
    assert second.decision.action == EnforcementAction.ALLOW_AND_LOG
    assert second.temporal is not None
    assert second.temporal.cumulative_score == 3.0
    service.approve(second.snapshot)

    third = service.observe_tool(
        server_id="demo",
        tool=_tool("Search repository files by keyword and path."),
    )

    assert third.assessment is not None
    assert third.assessment.change_class == ChangeClass.BENIGN_MAINTENANCE
    assert third.temporal is not None
    assert third.temporal.cumulative_score == 6.0
    assert third.temporal.exceeded is True
    assert third.decision.action == EnforcementAction.REQUIRE_RECONSENT


def test_unchanged_versions_do_not_consume_drift_budget():
    service = DriftGuardService(drift_budget=DriftBudget(window_size=3, budget=1.0))
    tool = _tool("Search repository files.")

    first = service.observe_tool(server_id="demo", tool=tool)
    service.approve(first.snapshot)
    second = service.observe_tool(server_id="demo", tool=tool)

    assert second.temporal is not None
    assert second.temporal.cumulative_score == 0.0
    assert second.temporal.exceeded is False
    assert second.decision.action == EnforcementAction.ALLOW
