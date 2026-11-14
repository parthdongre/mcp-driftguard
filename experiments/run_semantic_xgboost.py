from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from driftguard.dataset import PairDatasetRecord
from driftguard.embeddings import SentenceTransformerProvider
from driftguard.learning import GroupedSplit
from driftguard.semantic_xgboost import compare

MINILM = "sentence-transformers/all-MiniLM-L6-v2"
MINILM_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure what MiniLM adds to XGBoost.")
    for split in ("train", "validation", "test"):
        parser.add_argument(f"--{split}", type=Path, required=True, help="Labeled pair JSONL")
    encoder_options = parser.add_mutually_exclusive_group()
    encoder_options.add_argument("--structured-only", action="store_true")
    encoder_options.add_argument("--encoder-dir", type=Path, help="Local MiniLM snapshot")
    encoder_options.add_argument("--encoder-revision", help=f"Override the pinned revision of {MINILM}")
    parser.add_argument("--max-false-quarantine-rate", type=float, default=0.0)
    args = parser.parse_args()

    split_paths = {"train": args.train, "validation": args.validation, "test": args.test}
    inputs = {name: path.read_bytes() for name, path in split_paths.items()}
    split = GroupedSplit(**{
        name: [PairDatasetRecord.model_validate_json(line) for line in data.splitlines() if line.strip()]
        for name, data in inputs.items()
    })
    encoder = None
    if not args.structured_only:
        model_name = str(args.encoder_dir.resolve(strict=True)) if args.encoder_dir else MINILM
        encoder = SentenceTransformerProvider(
            model_name,
            revision=None if args.encoder_dir else args.encoder_revision or MINILM_REVISION,
            local_files_only=args.encoder_dir is not None,
        )
    report = compare(split, encoder=encoder, max_false_quarantine_rate=args.max_false_quarantine_rate)
    report["inputs_sha256"] = {
        name: hashlib.sha256(data).hexdigest() for name, data in inputs.items()
    }
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
