from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from driftguard.dataset import read_pair_jsonl
from driftguard.embeddings import EmbeddingCache, SentenceTransformerProvider
from driftguard.evaluation import evaluate_semantic_baselines
from driftguard.models import ChangeClass
from driftguard.splits import apply_split_manifest, read_split_manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare full-schema and field-aware cosine baselines on a frozen test split."
    )
    parser.add_argument("dataset", type=Path, help="PairDatasetRecord JSONL file")
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts/semantic_baselines.json"))
    parser.add_argument(
        "--model",
        default="sentence-transformers/all-MiniLM-L6-v2",
        help="Local sentence-transformers model identifier",
    )
    parser.add_argument("--full-schema-threshold", type=float, default=0.20)
    parser.add_argument("--field-threshold", type=float, default=0.20)
    args = parser.parse_args()

    records = read_pair_jsonl(args.dataset)
    manifest = read_split_manifest(args.split_manifest)
    split = apply_split_manifest(records, manifest)
    if not split.test:
        raise SystemExit("Frozen test split is empty")

    provider = SentenceTransformerProvider(args.model)
    cache = EmbeddingCache()
    consent_results = evaluate_semantic_baselines(
        split.test,
        embedding_provider=provider,
        embedding_cache=cache,
        full_schema_threshold=args.full_schema_threshold,
        field_threshold=args.field_threshold,
    )
    malicious_results = evaluate_semantic_baselines(
        split.test,
        embedding_provider=provider,
        embedding_cache=cache,
        full_schema_threshold=args.full_schema_threshold,
        field_threshold=args.field_threshold,
        positive_labels=(ChangeClass.MALICIOUS_DRIFT,),
    )

    payload = {
        "dataset": str(args.dataset),
        "split_manifest": str(args.split_manifest),
        "model": args.model,
        "test_records": len(split.test),
        "thresholds": {
            "full_schema": args.full_schema_threshold,
            "field_aware": args.field_threshold,
        },
        "consent_significant_c2_c3": [
            {"name": result.name, "metrics": asdict(result.metrics)}
            for result in consent_results
        ],
        "malicious_only_c3": [
            {"name": result.name, "metrics": asdict(result.metrics)}
            for result in malicious_results
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
