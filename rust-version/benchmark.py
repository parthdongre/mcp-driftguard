"""Compare equivalent operations through the Python and Rust process boundaries."""
from __future__ import annotations

import argparse
import json
import math
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = "import:benchmark"
LIVE_SCAN = "Discover official Filesystem MCP over stdio"
PYTHON_SCAN = """
import json
import sys
import time
from pathlib import Path

from driftguard.gateway import GuardStore
from driftguard.gateway_transport import LEGACY, StdioConfig, StdioPeer
from driftguard.harnesses import _catalog

db = Path(sys.argv[2])
profile = json.loads(Path(sys.argv[3]).read_text())
config = StdioConfig(profile["server_id"], tuple(profile["argv"]),
                     cwd=profile["cwd"], protocol_version=LEGACY)
peer = StdioPeer(config)
try:
    peer.initialize()
    tools = _catalog(peer, time.monotonic() + 15)
    with GuardStore(db) as store:
        store.register_server(peer.identity)
        records = store.ingest_catalog(profile["server_id"], tools, identity=peer.identity)
finally:
    peer.close()
print(json.dumps({"ok": True, "data": records}))
"""


def invoke(command, db, request, arguments=()):
    with tempfile.TemporaryFile() as stdin, tempfile.TemporaryFile() as stdout:
        stdin.write(json.dumps(request).encode())
        stdin.seek(0)
        started = time.perf_counter_ns()
        with subprocess.Popen([*command, "--db", str(db), *arguments], cwd=ROOT, stdin=stdin,
                              stdout=stdout, stderr=subprocess.DEVNULL) as process:
            _, status, usage = os.wait4(process.pid, 0)
            process.returncode = os.waitstatus_to_exitcode(status)
        elapsed = (time.perf_counter_ns() - started) / 1_000_000
        stdout.seek(0)
        try:
            response = json.load(stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError(f'{command[0]} returned no valid JSON for {request["action"]}') from error
    if process.returncode or not response["ok"]:
        raise RuntimeError(f'{request["action"]}: {response.get("error")}')
    rss_bytes = usage.ru_maxrss if sys.platform == "darwin" else usage.ru_maxrss * 1024
    return response["data"], elapsed, rss_bytes / 1024**2


def workload(command, folder, record, *, connection_graph=False):
    db = folder / "benchmark.sqlite3"
    definitions = [
        {"name": f"read_record_{index}", "description": "Read a selected database record.",
         "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}}}
        for index in range(350)
    ]

    def run(label, **request):
        result, elapsed, rss = invoke(command, db, request)
        record(label, elapsed, rss)
        return result

    run("Bridge startup and fresh database", action="overview")
    seed = {"action": "import_definitions", "server_id": "benchmark", "identity": "fixture"}
    assert len(run("Import 350 definitions", **seed, tools=definitions)) == 350
    tools = run("Load 350 catalog summaries", action="list_tools", summary=True)
    assert len(tools) == 350 and tools[0]["catalog"]["operations"] == ["read"]
    selected = {"server_id": SOURCE, "tool_name": definitions[0]["name"]}
    current = run("Open current review", action="review", **selected)

    def decision(label, action, version):
        return run(label, action=action, **selected, expected_sha256=version["sha256"],
                   expected_revision=version["revision"])

    current = decision("Approve a version", "approve", current)
    assert current["status"] == "approved"
    current = decision("Quarantine a version", "quarantine", current)
    assert current["status"] == "quarantined"
    current = decision("Release quarantine", "release_quarantine", current)
    assert current["status"] == "pending"
    changed = [{"name": definitions[0]["name"], "description": "Read one database row by ID.",
                "inputSchema": definitions[0]["inputSchema"]}, *definitions[1:]]
    assert len(run("Rescan 350 tools with one change", **seed, tools=changed)) == 350
    versions = run("Read tool version history", action="history", **selected)
    assert [version["description"] for version in versions] == [
        definitions[0]["description"], changed[0]["description"],
    ]
    alerts = run("Read change notifications", action="definition_alerts")
    assert alerts["unread"] == 1 and alerts["latest"]["detail"]["changed_fields"] == ["description"]
    assert run("Dismiss change notifications", action="dismiss_definition_alerts",
               through_id=alerts["latest"]["id"])["unread"] == 0
    assert run("Load security activity", action="activity")
    if connection_graph:
        graph = run("Load 350 tools in MCP graph", action="connection_graph")
        assert len(graph) == 1 and len(graph[0]["tools"]) == 350


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=15)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--filesystem-server", type=Path,
                        help="Installed official Filesystem MCP server dist/index.js")
    args = parser.parse_args()
    if args.runs < 2 or sys.platform not in {"darwin", "linux"}:
        parser.error("Use at least two runs on macOS or Linux.")
    rust = ROOT / "rust-version/target/release/driftguard-rust"
    commands = {"Python": [sys.executable, "-m", "driftguard.desktop_bridge"], "Rust": [str(rust)]}
    scan_commands = {"Python": [sys.executable, "-c", PYTHON_SCAN], "Rust": [str(rust)]}
    samples = {name: {} for name in commands}
    node = shutil.which("node")
    if args.filesystem_server and (not args.filesystem_server.is_file() or not node):
        parser.error("Filesystem benchmarking requires Node and an installed server script.")

    def collect(name, label, elapsed, rss):
        samples[name].setdefault(label, []).append((elapsed, rss))

    for repetition in range(args.runs + 1):
        order = list(commands) if repetition % 2 == 0 else list(reversed(commands))
        for name in order:
            with tempfile.TemporaryDirectory(prefix="driftguard-benchmark-") as directory:
                workload(commands[name], Path(directory), lambda label, elapsed, rss,
                         engine=name, warmed=bool(repetition):
                         collect(engine, label, elapsed, rss) if warmed else None,
                         connection_graph=name == "Rust")
        if args.filesystem_server:
            with tempfile.TemporaryDirectory(prefix="driftguard-live-benchmark-") as directory:
                folder = Path(directory).resolve()
                profile = folder / "server.json"
                profile.write_text(json.dumps({
                    "server_id": "filesystem", "argv": [node, str(args.filesystem_server.resolve()),
                                                        str(folder)],
                    "cwd": str(folder),
                }))
                for name in order:
                    arguments = [str(profile)] if name == "Python" else ["scan-stdio", str(profile)]
                    data, elapsed, rss = invoke(scan_commands[name], folder / f"{name}.sqlite3",
                                                {"action": "scan-stdio"}, arguments)
                    assert any(tool["tool_name"] == "read_text_file" for tool in data)
                    if repetition:
                        collect(name, LIVE_SCAN, elapsed, rss)
    results = {}
    for name, measurements in samples.items():
        results[name] = {}
        for label, readings in measurements.items():
            elapsed, memory = zip(*readings)
            results[name][label] = {
                "median_ms": round(statistics.median(elapsed), 2),
                "p95_ms": round(sorted(elapsed)[math.ceil(.95 * len(elapsed)) - 1], 2),
                "median_peak_rss_mib": round(statistics.median(memory), 2),
                "max_peak_rss_mib": round(max(memory), 2),
            }
    report = {"platform": platform.platform(), "runs_per_operation": args.runs, "results": results}
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    print("| Operation | Python median | Rust median | Python peak RSS | Rust peak RSS |")
    print("|---|---:|---:|---:|---:|")
    for label, py in results["Python"].items():
        rs = results["Rust"][label]
        print(f"| {label} | {py['median_ms']} ms | {rs['median_ms']} ms | "
              f"{py['median_peak_rss_mib']} MiB | {rs['median_peak_rss_mib']} MiB |")
    graph = results["Rust"]["Load 350 tools in MCP graph"]
    print(f"| Load 350 tools in MCP graph | — | {graph['median_ms']} ms | — | "
          f"{graph['median_peak_rss_mib']} MiB |")


if __name__ == "__main__":
    main()
