from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("forged", [False, True])
def test_annotation_cli_checks_adjudication_references_before_export(tmp_path, forged):
    candidate = {"candidate_id": "c1", "repository_id": "fixture/repo", "server_id": "fixture",
                 "tool_name": "read", "source_path": "fixture.py", "old_version_id": "one",
                 "new_version_id": "two", "old_tool": {"name": "read"},
                 "new_tool": {"name": "read", "description": "Clarified wording"}}
    left = {"annotation_id": "a1", "candidate_id": "c1", "annotator_id": "rater-one",
            "label": "C1", "rationale": "Automated regression fixture, not a real human label."}
    right = {**left, "annotation_id": "a2", "annotator_id": "rater-two"}
    adjudication = {"candidate_id": "c1",
                    "annotation_ids": ["unknown" if forged else "a1", "a2"],
                    "annotator_ids": ["rater-one", "rater-two"], "final_label": "C1",
                    "adjudicator_id": "fixture-adjudicator",
                    "rationale": "Automated regression fixture, not human research evidence."}
    for name, row in {"candidates": candidate, "left": left, "right": right,
                      "adjudications": adjudication}.items():
        (tmp_path / (name + ".jsonl")).write_text(json.dumps(row) + "\n")
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "reviewed.jsonl"
    result = subprocess.run([
        sys.executable, str(root / "experiments/score_annotations.py"),
        str(tmp_path / "left.jsonl"), str(tmp_path / "right.jsonl"),
        "--output", str(tmp_path / "agreement.json"),
        "--candidates", str(tmp_path / "candidates.jsonl"),
        "--adjudications", str(tmp_path / "adjudications.jsonl"),
        "--reviewed-output", str(output),
    ], cwd=root, env={**os.environ, "PYTHONPATH": str(root / "src")},
       capture_output=True, timeout=20)
    assert (result.returncode != 0) is forged
    assert output.exists() is not forged
