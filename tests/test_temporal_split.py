from __future__ import annotations

from driftguard.dataset import PairDatasetRecord
from driftguard.models import ChangeClass
from driftguard.splits import TemporalCutoffManifest, apply_temporal_cutoff_manifest


def _record(record_id: str, timestamp: str) -> PairDatasetRecord:
    tool = {
        "name": "demo",
        "description": "Demo tool",
        "inputSchema": {"type": "object", "properties": {}},
    }
    new_tool = {**tool, "description": f"Demo tool {record_id}"}
    return PairDatasetRecord(
        record_id=record_id,
        repository_id="repo",
        server_id="server",
        tool_name="demo",
        old_tool=tool,
        new_tool=new_tool,
        label=ChangeClass.BENIGN_MAINTENANCE,
        provenance="real_history",
        new_committed_at=timestamp,
    )


def test_temporal_cutoff_creates_future_holdout() -> None:
    records = [
        _record("train", "2026-01-10T00:00:00+00:00"),
        _record("validation", "2026-04-10T00:00:00+00:00"),
        _record("test", "2026-07-10T00:00:00+00:00"),
    ]
    manifest = TemporalCutoffManifest(
        validation_start="2026-03-01T00:00:00+00:00",
        test_start="2026-06-01T00:00:00+00:00",
    )
    split = apply_temporal_cutoff_manifest(records, manifest)
    assert [record.record_id for record in split.train] == ["train"]
    assert [record.record_id for record in split.validation] == ["validation"]
    assert [record.record_id for record in split.test] == ["test"]
