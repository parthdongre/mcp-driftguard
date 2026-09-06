from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from driftguard.annotation_workflow import (
    adjudications_to_pair_records,
    annotation_agreement,
    disagreement_candidate_ids,
    read_adjudications_jsonl,
    read_human_annotations_jsonl,
)
from driftguard.dataset import read_candidate_jsonl, write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Score two independent DriftGuard annotation files and optionally build "
            "the adjudicated reviewed real-history pair dataset."
        )
    )
    parser.add_argument("annotations_a", type=Path)
    parser.add_argument("annotations_b", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/annotation_agreement.json"),
    )
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--adjudications", type=Path)
    parser.add_argument("--reviewed-output", type=Path)
    args = parser.parse_args()

    left = read_human_annotations_jsonl(args.annotations_a)
    right = read_human_annotations_jsonl(args.annotations_b)
    agreement = annotation_agreement(left, right)
    disagreement_ids = disagreement_candidate_ids(left, right)
    c2_c3_ids = disagreement_candidate_ids(left, right, c2_c3_only=True)

    payload: dict[str, object] = {
        "annotations_a": str(args.annotations_a),
        "annotations_b": str(args.annotations_b),
        "agreement": asdict(agreement),
        "disagreement_candidate_ids": disagreement_ids,
        "c2_c3_disagreement_candidate_ids": c2_c3_ids,
    }

    requested_reviewed = any(
        value is not None
        for value in (args.candidates, args.adjudications, args.reviewed_output)
    )
    if requested_reviewed:
        if not all(
            value is not None
            for value in (args.candidates, args.adjudications, args.reviewed_output)
        ):
            raise SystemExit(
                "--candidates, --adjudications, and --reviewed-output must be supplied together"
            )
        assert args.candidates is not None
        assert args.adjudications is not None
        assert args.reviewed_output is not None
        candidates = read_candidate_jsonl(args.candidates)
        adjudications = read_adjudications_jsonl(args.adjudications)
        reviewed = adjudications_to_pair_records(candidates, adjudications)
        write_jsonl(args.reviewed_output, reviewed)
        payload["reviewed_dataset"] = {
            "candidates": str(args.candidates),
            "adjudications": str(args.adjudications),
            "output": str(args.reviewed_output),
            "records": len(reviewed),
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
