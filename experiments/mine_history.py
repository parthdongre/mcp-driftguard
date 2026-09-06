from __future__ import annotations

import argparse
import json
from pathlib import Path

from driftguard.corpus import historical_versions_to_candidates
from driftguard.dataset import write_jsonl
from driftguard.history import GitManifestHistoryMiner, GitSourceHistoryMiner
from driftguard.source_extractors import PythonDecoratorToolExtractor


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Mine versioned MCP tool definitions from a local Git repository without "
            "executing repository code."
        )
    )
    parser.add_argument("repository", type=Path, help="Local Git repository path")
    parser.add_argument("--repository-id", required=True, help="Stable owner/repository identifier")
    parser.add_argument(
        "--kind",
        choices=["json", "python"],
        required=True,
        help="Static extraction mode",
    )
    parser.add_argument(
        "--path",
        dest="paths",
        action="append",
        required=True,
        help="Repository-relative file path to mine; repeat for multiple files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output JSONL annotation-candidate queue",
    )
    args = parser.parse_args()

    if args.kind == "json":
        miner = GitManifestHistoryMiner(
            args.repository,
            repository_id=args.repository_id,
            manifest_paths=args.paths,
        )
    else:
        miner = GitSourceHistoryMiner(
            args.repository,
            repository_id=args.repository_id,
            source_paths=args.paths,
            extractor=PythonDecoratorToolExtractor(),
        )

    versions = miner.mine()
    candidates = historical_versions_to_candidates(versions)
    write_jsonl(args.output, candidates)

    summary = {
        "repository_id": args.repository_id,
        "kind": args.kind,
        "paths": args.paths,
        "versions": len(versions),
        "annotation_candidates": len(candidates),
        "output": str(args.output),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
