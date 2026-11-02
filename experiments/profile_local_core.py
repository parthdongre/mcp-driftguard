"""Reproducible CPU-only systems measurements on explicit generated fixtures.

These are engineering costs, not detection accuracy or production guarantees.
No models download, no remote MCP server runs, and no secrets are collected.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import platform
import subprocess
import time
import tracemalloc
from pathlib import Path
from statistics import median

from driftguard.canonicalize import canonical_json, make_snapshot
from driftguard.diff import build_delta
from driftguard.features import extract_pair_features
from driftguard.temporal import research_risk_signal


def fixture(index: int) -> dict:
    return {
        "name": f"search_{index}", "description": "Search local project files.",
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}},
                        "required": ["query"]},
        "annotations": {"readOnlyHint": True},
    }


def measure(count: int, repeats: int) -> dict:
    tools = [fixture(index) for index in range(count)]
    canonical_bytes = sum(len(canonical_json(tool).encode()) for tool in tools)
    tracemalloc.start()
    start = time.perf_counter_ns()
    baseline = [make_snapshot(server_id="profile-fixture", tool=tool) for tool in tools]
    cold_ms = (time.perf_counter_ns() - start) / 1e6
    timings = []
    # Changed definitions exercise pair extraction. We do not call these observations
    # 'warm cache': the deterministic pipeline has no feature cache.
    for repeat in range(repeats):
        old = baseline[repeat % count]
        changed = {**old.raw_tool, "description": "Search local project files and metadata."}
        start = time.perf_counter_ns()
        current = make_snapshot(server_id="profile-fixture", tool=changed)
        research_risk_signal(extract_pair_features(build_delta(old, current)))
        timings.append((time.perf_counter_ns() - start) / 1e6)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    ordered = sorted(timings)
    return {
        "catalog_tools": count, "repeats": repeats,
        "cold_snapshot_catalog_ms": cold_ms,
        "pair_median_ms": median(timings),
        "pair_p95_ms": ordered[math.ceil(0.95 * len(ordered)) - 1],
        "pairs_per_second": repeats / (sum(timings) / 1000),
        "tracemalloc_peak_bytes": peak,
        "canonical_snapshot_bytes": canonical_bytes,
        "peak_scope": "Python allocations during snapshots+pair extraction; excludes native/RSS",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=100)
    parser.add_argument("--catalog-sizes", type=int, nargs="+", default=[10, 100, 1000])
    args = parser.parse_args()
    if args.repeats < 20 or any(n < 1 or n > 10_000 for n in args.catalog_sizes):
        parser.error("Use >=20 repeats and catalog sizes between 1 and 10000")
    root = Path(__file__).resolve().parents[1]
    def git(*parts: str) -> str:
        return subprocess.check_output(["git", "-C", str(root), *parts], text=True)
    payload = {
        "evidence_level": "generated_fixture_engineering_measurements",
        "paper_claim_eligible": False,
        "git_head": git("rev-parse", "HEAD").strip(),
        "working_tree_diff_sha256": hashlib.sha256(git("diff", "HEAD").encode()).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python": platform.python_version(), "platform": platform.platform(),
        "pydantic": importlib.metadata.version("pydantic"),
        "embedding_model": None,
        "cache": "No embedding/feature cache used; OS/interpreter warm-up uncontrolled",
        "timing_instrumentation": "tracemalloc enabled; results include its overhead",
        "measurements": [measure(count, args.repeats) for count in args.catalog_sizes],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
