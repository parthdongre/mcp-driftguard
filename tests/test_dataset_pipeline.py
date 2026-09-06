from driftguard.dataset import PairDatasetRecord
from driftguard.evaluation import binary_metrics, evaluate_standard_baselines
from driftguard.labeling import EvidenceTag, recommended_label
from driftguard.models import ChangeClass
from driftguard.mutations import (
    add_cross_tool_steering,
    add_external_upload,
    add_optional_format_parameter,
    build_low_and_slow_trajectory,
)


def base_tool():
    return {
        "name": "search_repo",
        "description": "Search repository files for matching source code.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        "annotations": {"readOnlyHint": True},
    }


def pair(record_id, repository_id, new_tool, label):
    return PairDatasetRecord(
        record_id=record_id,
        repository_id=repository_id,
        server_id=f"server-{repository_id}",
        tool_name="search_repo",
        old_tool=base_tool(),
        new_tool=new_tool,
        label=label,
        provenance="synthetic_attack" if label is ChangeClass.MALICIOUS_DRIFT else "controlled_benign",
    )


def test_labeling_framework_preserves_reconsent_boundary():
    benign = recommended_label([EvidenceTag.DOCUMENTATION_CLARIFICATION])
    expansion = recommended_label(
        [EvidenceTag.NEW_CAPABILITY, EvidenceTag.NEW_EXTERNAL_DESTINATION],
        known_legitimate_change=True,
    )
    malicious = recommended_label([EvidenceTag.CROSS_TOOL_STEERING])

    assert benign.label is ChangeClass.BENIGN_MAINTENANCE
    assert expansion.label is ChangeClass.CAPABILITY_EXPANSION
    assert malicious.label is ChangeClass.MALICIOUS_DRIFT


def test_controlled_mutations_remain_schema_shaped():
    tool = base_tool()
    optional = add_optional_format_parameter(tool)
    external = add_external_upload(tool)
    steering = add_cross_tool_steering(tool)

    assert "format" in optional["inputSchema"]["properties"]
    assert "https://telemetry.example.invalid" in external["description"]
    assert "tool search_repo" in steering["description"]
    assert tool["inputSchema"]["properties"] == {"query": {"type": "string"}}


def test_low_and_slow_fixture_accumulates_capabilities():
    trajectory = build_low_and_slow_trajectory(
        repository_id="owner/repo",
        server_id="server-1",
        tool=base_tool(),
    )

    assert trajectory.steps[0].version_id == "v0"
    assert len(trajectory.steps) >= 6
    assert trajectory.final_label is ChangeClass.MALICIOUS_DRIFT
    assert "format" in trajectory.steps[-1].tool["inputSchema"]["properties"]
    assert "all repositories and all files recursively" in trajectory.steps[-1].tool["description"]
    assert "telemetry.example.invalid" in trajectory.steps[-1].tool["description"]
    assert "api_token" not in trajectory.steps[-1].tool["inputSchema"]["properties"]


def test_binary_metrics_are_reproducible():
    metrics = binary_metrics([True, True, False, False], [True, False, True, False])
    assert metrics.tp == 1
    assert metrics.fp == 1
    assert metrics.tn == 1
    assert metrics.fn == 1
    assert metrics.f1 == 0.5
    assert metrics.false_positive_rate == 0.5


def test_standard_baselines_share_same_records():
    records = [
        pair(
            "benign-1",
            "repo-a",
            add_optional_format_parameter(base_tool()),
            ChangeClass.BENIGN_MAINTENANCE,
        ),
        pair(
            "malicious-1",
            "repo-b",
            add_external_upload(base_tool()),
            ChangeClass.MALICIOUS_DRIFT,
        ),
    ]

    results = evaluate_standard_baselines(records, lexical_threshold=0.01, rule_threshold=20.0)
    assert {result.name for result in results} == {
        "hash_any_change",
        "lexical_threshold",
        "rule_risk",
    }
    assert all(result.metrics.tp + result.metrics.fn == 1 for result in results)
