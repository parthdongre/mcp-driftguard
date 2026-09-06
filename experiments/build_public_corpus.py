from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

from driftguard.corpus import historical_versions_to_candidates
from driftguard.corpus_discovery import discover_mcp_sources, extractable_paths_by_kind
from driftguard.dataset import AnnotationCandidate, write_jsonl
from driftguard.history import GitManifestHistoryMiner, GitSourceHistoryMiner, HistoricalToolVersion
from driftguard.source_extractors import PythonDecoratorToolExtractor, TypeScriptRegisterToolExtractor


def _run(command: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def _repo_directory(workspace: Path, repository_id: str) -> Path:
    return workspace / repository_id.replace("/", "__")


def _ensure_repository(
    entry: dict[str, Any],
    *,
    workspace: Path,
    no_network: bool,
    refresh: bool,
) -> Path:
    repository_id = str(entry["repository_id"])
    target = _repo_directory(workspace, repository_id)
    if target.exists():
        if not (target / ".git").is_dir():
            raise RuntimeError(f"Existing corpus path is not a Git repository: {target}")
        if refresh:
            if no_network:
                raise RuntimeError("--refresh cannot be combined with --no-network")
            _run(["git", "fetch", "--all", "--prune", "--tags"], cwd=target)
            _run(["git", "pull", "--ff-only"], cwd=target)
        return target

    if no_network:
        raise RuntimeError(f"Repository is missing in --no-network mode: {repository_id}")

    clone_url = str(entry["clone_url"])
    workspace.mkdir(parents=True, exist_ok=True)
    _run(["git", "clone", "--no-tags", clone_url, str(target)])
    return target


def _mine_repository(repository_path: Path, repository_id: str) -> tuple[list[HistoricalToolVersion], list[dict[str, Any]]]:
    discoveries = discover_mcp_sources(repository_path)
    paths = extractable_paths_by_kind(discoveries)
    versions: list[HistoricalToolVersion] = []

    if paths["json"]:
        versions.extend(
            GitManifestHistoryMiner(
                repository_path,
                repository_id=repository_id,
                manifest_paths=paths["json"],
            ).mine()
        )
    if paths["python"]:
        versions.extend(
            GitSourceHistoryMiner(
                repository_path,
                repository_id=repository_id,
                source_paths=paths["python"],
                extractor=PythonDecoratorToolExtractor(),
            ).mine()
        )
    if paths["typescript"]:
        versions.extend(
            GitSourceHistoryMiner(
                repository_path,
                repository_id=repository_id,
                source_paths=paths["typescript"],
                extractor=TypeScriptRegisterToolExtractor(),
            ).mine()
        )

    return versions, [asdict(item) for item in discoveries]


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    repositories = payload.get("repositories")
    if not isinstance(repositories, list):
        raise ValueError("Corpus manifest must contain a repositories list")
    return [entry for entry in repositories if isinstance(entry, dict)]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Clone public MCP repositories, statically discover tool registrations, "
            "mine Git history, and build an unlabeled annotation queue without "
            "executing target repository code."
        )
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/public_corpus_sources.json"),
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path(".corpus/repos"),
        help="Local clone directory; keep outside committed dataset artifacts",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/public_history_candidates.jsonl"),
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("artifacts/public_history_summary.json"),
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Repository id to process; repeat to select multiple repositories",
    )
    parser.add_argument("--max-repos", type=int, default=None)
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    entries = _load_manifest(args.manifest)
    selected = set(args.only)
    if selected:
        entries = [entry for entry in entries if entry.get("repository_id") in selected]
    if args.max_repos is not None:
        entries = entries[: args.max_repos]
    if not entries:
        raise SystemExit("No repositories selected")

    all_candidates: list[AnnotationCandidate] = []
    repository_summaries: list[dict[str, Any]] = []

    for entry in entries:
        repository_id = str(entry["repository_id"])
        repo_path = _ensure_repository(
            entry,
            workspace=args.workspace,
            no_network=args.no_network,
            refresh=args.refresh,
        )
        versions, discoveries = _mine_repository(repo_path, repository_id)
        candidates = historical_versions_to_candidates(versions)
        all_candidates.extend(candidates)

        extractable = [item for item in discoveries if item["status"] == "extractable"]
        unsupported = [item for item in discoveries if item["status"] == "unsupported_pattern"]
        parse_errors = [item for item in discoveries if item["status"] == "parse_error"]
        repository_summaries.append(
            {
                "repository_id": repository_id,
                "priority": entry.get("priority"),
                "declared_extractor_readiness": entry.get("extractor_readiness"),
                "discovered_source_files": len(discoveries),
                "extractable_source_files": len(extractable),
                "unsupported_pattern_files": len(unsupported),
                "parse_error_files": len(parse_errors),
                "historical_schema_versions": len(versions),
                "annotation_candidates": len(candidates),
                "discoveries": discoveries,
            }
        )

    write_jsonl(args.output, all_candidates)
    summary = {
        "manifest": str(args.manifest),
        "repositories_processed": len(repository_summaries),
        "annotation_candidates": len(all_candidates),
        "repositories": repository_summaries,
        "safety": {
            "target_code_executed": false,
            "target_code_imported": false,
            "method": "static source/JSON parsing plus git show over historical blobs"
        }
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
