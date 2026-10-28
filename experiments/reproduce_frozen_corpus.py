"""Reproduce the private frozen acquisition using pinned public Git histories.

Only Git and DriftGuard's own static parser run. Missing checkouts require the
explicit --fetch flag. This does not label data or execute target server code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SOURCE_FILES = (
    "experiments/build_public_corpus.py", "src/driftguard/canonicalize.py",
    "src/driftguard/corpus.py", "src/driftguard/corpus_discovery.py",
    "src/driftguard/dataset.py", "src/driftguard/diff.py",
    "src/driftguard/history.py", "src/driftguard/source_extractors.py",
)


def run(arguments: list[str], *, timeout: int = 60) -> str:
    return subprocess.check_output(arguments, text=True, timeout=timeout).strip()


def records(path: Path) -> dict[str, dict]:
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["candidate_id"] in result:
            raise ValueError("Duplicate candidate ID")
        result[row["candidate_id"]] = row
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True,
                        help="Extracted private corpus handoff directory")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true", help="Clone missing pinned public histories")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    provenance = json.loads((args.evidence / "extractor-provenance.json").read_text())
    for name in SOURCE_FILES:
        actual = hashlib.sha256((project / name).read_bytes()).hexdigest()
        if actual != provenance["files"][name]:
            raise SystemExit(f"Extractor source mismatch: {name}; use the archived matching revision")
    summary = json.loads((args.evidence / "summary.json").read_text())
    args.workspace.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)
    for entry in summary["repositories"]:
        if entry["status"] != "extracted":
            continue
        identity = entry["repository_id"]
        sha = entry["selected_snapshot_sha"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", identity):
            raise ValueError("Invalid source repository identity")
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("Invalid frozen source commit")
        target = args.workspace / identity.replace("/", "__")
        expected_origin = f"https://github.com/{identity}.git"
        if not (target / ".git").is_dir():
            if not args.fetch:
                raise SystemExit(f"Missing {identity}; explicitly pass --fetch to acquire it")
            run(["git", "clone", "--no-tags", expected_origin, str(target)], timeout=180)
        origin = run(["git", "-C", str(target), "remote", "get-url", "origin"])
        # Git proxy rewrites are permitted only if the logical source is preserved.
        if origin.rstrip("/").removesuffix(".git") != expected_origin.removesuffix(".git"):
            raise ValueError(f"Repository origin mismatch for {identity}")
        if run(["git", "-C", str(target), "status", "--porcelain"]):
            raise ValueError(f"Refusing to change a modified source checkout: {identity}")
        if run(["git", "-C", str(target), "rev-parse", "HEAD"]) != sha:
            run(["git", "-C", str(target), "checkout", "--detach", sha])
        print(f"Pinned {identity} at {sha[:12]}", flush=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(project / "src")
    output_file = args.output / "reproduced-candidates.jsonl"
    subprocess.run([
        sys.executable, str(project / "experiments/build_public_corpus.py"),
        "--manifest", str(args.evidence.resolve() / "processed-manifest.json"),
        "--workspace", str(args.workspace.resolve()), "--output", str(output_file.resolve()),
        "--summary", str((args.output / "extraction-summary.json").resolve()), "--no-network",
    ], cwd=project, env=env, check=True, timeout=900, stdout=subprocess.DEVNULL)
    expected = {**records(args.evidence / "primary-candidates.jsonl"),
                **records(args.evidence / "reference-candidates.jsonl")}
    reproduced = records(output_file)
    verdict = {"exact_record_match": expected == reproduced, "expected": len(expected),
               "reproduced": len(reproduced), "human_labels": 0,
               "source_runtime_executed": False, "paper_claim_eligible": False}
    (args.output / "verification.json").write_text(json.dumps(verdict, indent=2) + "\n")
    print(json.dumps(verdict))
    if not verdict["exact_record_match"]:
        raise SystemExit("Frozen corpus does not reproduce; do not silently replace it")


if __name__ == "__main__":
    main()
