from driftguard.cli import main
from driftguard.runtime import DriftGuardService, SQLiteSnapshotStore


def _tool():
    return {
        "name": "search",
        "description": "Search documents",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }


def test_cli_audit_verify_reports_valid_chain(tmp_path, capsys):
    database = tmp_path / "driftguard.db"
    store = SQLiteSnapshotStore(database)
    service = DriftGuardService(store=store)
    first = service.observe_tool(server_id="demo", tool=_tool())
    service.approve(first.snapshot, reviewer="alice")
    store.close()

    exit_code = main(
        [
            "audit",
            "verify",
            "--db",
            str(database),
            "--server",
            "demo",
            "--tool",
            "search",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert '"valid": true' in output
    assert '"event_count": 1' in output


def test_cli_graph_benchmark_accepts_explicit_dataset(tmp_path, capsys):
    dataset = tmp_path / "graph.jsonl"
    dataset.write_text(
        '{"sample_id":"safe","family":"none","risky":false,'
        '"old_tools":[{"name":"search","description":"Search"}],'
        '"new_tools":[{"name":"search","description":"Search"}]}\n',
        encoding="utf-8",
    )

    exit_code = main(["benchmark", "graph", str(dataset)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert '"total": 1' in output
    assert '"accuracy": 1.0' in output
