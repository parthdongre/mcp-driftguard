from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from .evaluation import evaluate_file
from .graph_evaluation import evaluate_graph_file
from .revisions import compare_to_trusted, diff_revisions
from .runtime import SQLiteSnapshotStore, verify_review_chain


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="driftguard",
        description="MCP DriftGuard local research, revision, and audit CLI.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    benchmark = subcommands.add_parser("benchmark", help="Run reproducible benchmark suites.")
    benchmark_sub = benchmark.add_subparsers(dest="benchmark_name", required=True)

    pairwise = benchmark_sub.add_parser("pairwise", help="Evaluate the rule baseline.")
    pairwise.add_argument(
        "path",
        nargs="?",
        default="data/synthetic_v0.jsonl",
        help="Path to a pairwise JSONL benchmark.",
    )

    graph = benchmark_sub.add_parser("graph", help="Evaluate graph topology drift.")
    graph.add_argument(
        "path",
        nargs="?",
        default="data/graph_synthetic_v0.jsonl",
        help="Path to a graph-evolution JSONL benchmark.",
    )

    for command_name, help_text in (
        ("status", "Show current discovery status against previous and trusted state."),
        ("log", "Show discovery revision history."),
    ):
        command = subcommands.add_parser(command_name, help=help_text)
        command.add_argument("--db", required=True, help="Path to the DriftGuard SQLite database.")
        command.add_argument("--server", required=True, help="MCP server identifier.")

    diff = subcommands.add_parser("diff", help="Compare two discovery revisions.")
    diff.add_argument("--db", required=True, help="Path to the DriftGuard SQLite database.")
    diff.add_argument("--server", required=True, help="MCP server identifier.")
    diff.add_argument("--from", dest="from_revision", required=True, help="Older revision ID.")
    diff.add_argument("--to", dest="to_revision", required=True, help="Newer revision ID.")

    audit = subcommands.add_parser("audit", help="Inspect durable review history.")
    audit_sub = audit.add_subparsers(dest="audit_command", required=True)

    verify = audit_sub.add_parser("verify", help="Verify a tool review hash chain.")
    verify.add_argument("--db", required=True, help="Path to the DriftGuard SQLite database.")
    verify.add_argument("--server", required=True, help="MCP server identifier.")
    verify.add_argument("--tool", required=True, help="Tool name.")

    reviews = audit_sub.add_parser("reviews", help="Print review events for one tool.")
    reviews.add_argument("--db", required=True, help="Path to the DriftGuard SQLite database.")
    reviews.add_argument("--server", required=True, help="MCP server identifier.")
    reviews.add_argument("--tool", required=True, help="Tool name.")

    return parser


def _run_benchmark(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if args.benchmark_name == "pairwise":
        report = evaluate_file(path)
    else:
        report = evaluate_graph_file(path)
    print(report.model_dump_json(indent=2))
    return 0


def _run_revision_command(args: argparse.Namespace) -> int:
    store = SQLiteSnapshotStore(args.db)
    try:
        if args.command == "log":
            revisions = store.revision_history(args.server)
            print("[\n" + ",\n".join(item.model_dump_json(indent=2) for item in revisions) + "\n]")
            return 0

        if args.command == "status":
            revisions = store.revision_history(args.server)
            if not revisions:
                print('{"error":"no revisions found"}')
                return 1
            latest = revisions[-1]
            previous = revisions[-2] if len(revisions) > 1 else None
            payload = {
                "revision": latest.model_dump(mode="json"),
                "previous_delta": (
                    diff_revisions(previous, latest).model_dump(mode="json")
                    if previous is not None
                    else None
                ),
                "trusted_status": compare_to_trusted(
                    latest,
                    store.trusted_tools(args.server),
                ).model_dump(mode="json"),
            }
            import json

            print(json.dumps(payload, indent=2))
            return 0

        old = store.get_revision(args.server, args.from_revision)
        new = store.get_revision(args.server, args.to_revision)
        if old is None or new is None:
            print('{"error":"one or both revisions not found"}')
            return 1
        print(diff_revisions(old, new).model_dump_json(indent=2))
        return 0
    finally:
        store.close()


def _run_audit(args: argparse.Namespace) -> int:
    store = SQLiteSnapshotStore(args.db)
    try:
        events = store.reviews(args.server, args.tool)
        if args.audit_command == "reviews":
            print("[\n" + ",\n".join(event.model_dump_json(indent=2) for event in events) + "\n]")
            return 0

        report = verify_review_chain(events)
        print(report.model_dump_json(indent=2))
        return 0 if report.valid else 2
    finally:
        store.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "benchmark":
        return _run_benchmark(args)
    if args.command in {"status", "log", "diff"}:
        return _run_revision_command(args)
    if args.command == "audit":
        return _run_audit(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
