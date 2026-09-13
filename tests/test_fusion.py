from driftguard.fusion import FusionScenario, evaluate_fusion_samples
from driftguard.models import ChangeClass, RiskAssessment


def _tool(description: str):
    return {
        "name": "search",
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    }


def _fake_detector(delta):
    description = str(delta.new.raw_tool.get("description", ""))
    if delta.old.sha256 == delta.new.sha256:
        return RiskAssessment(
            change_class=ChangeClass.NO_MEANINGFUL_CHANGE,
            risk_score=0.0,
            recommended_action="allow",
        )
    if "HIGH" in description:
        return RiskAssessment(
            change_class=ChangeClass.CAPABILITY_EXPANSION,
            risk_score=60.0,
            recommended_action="require_reconsent",
        )
    return RiskAssessment(
        change_class=ChangeClass.BENIGN_MAINTENANCE,
        risk_score=6.0,
        recommended_action="allow_and_log",
    )


def test_fusion_ablation_separates_pairwise_temporal_and_graph_signals():
    samples = [
        FusionScenario(
            sample_id="pair",
            family="pairwise",
            intervention_required=True,
            tracked_tool="search",
            versions=[
                [_tool("base")],
                [_tool("HIGH capability")],
            ],
        ),
        FusionScenario(
            sample_id="temporal",
            family="low_and_slow",
            intervention_required=True,
            tracked_tool="search",
            versions=[
                [_tool("v1")],
                [_tool("v2")],
                [_tool("v3")],
            ],
        ),
        FusionScenario(
            sample_id="graph",
            family="graph_route",
            intervention_required=True,
            tracked_tool="search",
            versions=[
                [
                    _tool("base"),
                    {"name": "credential_export", "description": "Export credential"},
                ],
                [
                    _tool("base via tool credential_export"),
                    {"name": "credential_export", "description": "Export credential"},
                ],
            ],
        ),
        FusionScenario(
            sample_id="safe",
            family="benign",
            intervention_required=False,
            tracked_tool="search",
            versions=[
                [_tool("base")],
                [_tool("base")],
            ],
        ),
    ]

    report = evaluate_fusion_samples(
        samples,
        detector=_fake_detector,
        temporal_budget=10.0,
        temporal_window_size=3,
    )
    by_id = {item.sample_id: item for item in report.predictions}

    assert by_id["pair"].pairwise is True
    assert by_id["temporal"].pairwise is False
    assert by_id["temporal"].temporal is True
    assert by_id["graph"].graph is True
    assert by_id["safe"].full_fusion is False
    assert report.metrics["full_fusion"].recall == 1.0
