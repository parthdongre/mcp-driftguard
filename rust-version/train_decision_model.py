"""Fit an experimental Rust gateway classifier from labeled DriftGuard pairs."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss

from driftguard.dataset import read_pair_jsonl


def feature_rows(engine, records):
    with tempfile.TemporaryDirectory(prefix="driftguard-model-features-") as directory:
        command = [str(engine.resolve()), "--db", str(Path(directory) / "features.sqlite3")]
        rows = []
        for start in range(0, len(records), 8):
            batch = records[start:start + 8]
            request = {"action": "model_features", "pairs": [
                {"old_tool": row.old_tool, "new_tool": row.new_tool} for row in batch
            ]}
            result = subprocess.run(
                command, input=json.dumps(request, ensure_ascii=False), text=True,
                capture_output=True, check=True, timeout=30,
            )
            rows.extend(json.loads(result.stdout)["data"])
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--train", required=True, type=Path)
    parser.add_argument("--validation", required=True, type=Path)
    parser.add_argument("--id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-max", required=True, type=float)
    parser.add_argument("--quarantine-min", required=True, type=float)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", args.id):
        parser.error("Use a model ID with 1–80 ASCII letters, digits, dots, underscores, or hyphens.")
    if not (0 <= args.allow_max <= 0.2 and 0.8 <= args.quarantine_min <= 1):
        parser.error("Allow threshold must be 0–0.2 and quarantine threshold 0.8–1.")
    train = read_pair_jsonl(args.train)
    validation = read_pair_jsonl(args.validation)
    if {row.leakage_group for row in train} & {row.leakage_group for row in validation}:
        parser.error("Training and validation repositories must be disjoint.")
    train_y = [row.label.value == "C3" for row in train]
    validation_y = [row.label.value == "C3" for row in validation]
    if len(set(train_y)) != 2 or len(set(validation_y)) != 2:
        parser.error("Both splits need malicious and non-malicious examples.")
    classifier = LogisticRegression(random_state=42)
    classifier.fit(feature_rows(args.engine, train), train_y)
    scores = classifier.predict_proba(feature_rows(args.engine, validation))[:, 1]
    artifact = {
        "version": 1, "id": args.id, "weights": classifier.coef_[0].tolist(),
        "intercept": float(classifier.intercept_[0]), "allow_max": args.allow_max,
        "quarantine_min": args.quarantine_min,
    }
    # Validate through the same installer that activates a workspace model.
    with tempfile.TemporaryDirectory(prefix="driftguard-model-check-") as directory:
        directory = Path(directory)
        candidate = directory / "model.json"
        candidate.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
        subprocess.run([
            str(args.engine.resolve()), "--db", str(directory / "check.sqlite3"),
            "model", "set", str(candidate),
        ], check=True, capture_output=True, timeout=30)
        args.output.write_text(candidate.read_text(encoding="utf-8"), encoding="utf-8")
    print(json.dumps({
        "train_pairs": len(train), "validation_pairs": len(validation),
        "validation_auprc": float(average_precision_score(validation_y, scores)),
        "validation_brier": float(brier_score_loss(validation_y, scores)),
    }, indent=2))


if __name__ == "__main__":
    main()
