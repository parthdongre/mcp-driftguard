from __future__ import annotations

import argparse
import time
from collections.abc import Sequence
from pathlib import Path

from .blame import blame_tool
from .changefeed import changes_after
from .evaluation import evaluate_file
from .fusion_evaluation import evaluate_fusion_file
from .graph_evaluation import evaluate_graph_file
from .render import (
    render_catalog_freshness,
    render_change_event,
    render_revision_check,
    render_revision_delta,
    render_revision_log,
    render_revision_view,
    render_surface_status,
    render_timeline_event,
    render_tool_blame,
)
from .revisions import SurfaceObservation, compare_to_trusted, diff_revisions
from .runtime import SQLiteSnapshotStore, verify_review_chain
from .signals import catalog_freshness
from .stdio_proxy import run_stdio_proxy
from .timeline import build_server_timeline
from .views import build_revision_view


def _add_store_args(command: argparse.ArgumentParser) -> None:
    command.add_argument("--db", required=True, help="Path to the DriftGuard SQLite database.")
    command.add_argument("--server", required=True, help="MCP server identifier.")


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

    fusion = benchmark_sub.add_parser(
        "fusion",
        help="Compare pairwise, temporal, graph, and fused detector layers.",
    )
    fusion.add_argument(
        "path",
        nargs="?",
        default="data/fusion_synthetic_v0.jsonl",
        help="Path to a multi-revision fusion JSONL benchmark.",
    )
    fusion.add_argument(
        "--temporal-budget",
        type=float,
        default=20.0,
        help="Experimental cumulative drift threshold (default: 20).",
    )

    status = subcommands.add_parser(
        "status",
        help="Show current discovery status against previous and trusted state.",
    )
    _add_store_args(status)
    status.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    freshness = subcommands.add_parser(
        "freshness",
        help="Show whether the known tool catalog is stale after a server change notification.",
    )
    _add_store_args(freshness)
    freshness.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    log = subcommands.add_parser("log", help="Show discovery revision history.")
    _add_store_args(log)
    log.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    diff = subcommands.add_parser("diff", help="Compare two discovery revisions.")
    _add_store_args(diff)
    diff.add_argument("--from", dest="from_revision", required=True, help="Older revision ID.")
    diff.add_argument("--to", dest="to_revision", required=True, help="Newer revision ID.")
    diff.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    changes = subcommands.add_parser("changes", help="Show incremental discovery changes.")
    _add_store_args(changes)
    changes.add_argument("--after", help="Only show revisions after this revision ID.")
    changes.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    watch = subcommands.add_parser("watch", help="Continuously print new discovery revisions.")
    _add_store_args(watch)
    watch.add_argument("--after", help="Start after this revision ID.")
    watch.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Polling interval in seconds (default: 1.0).",
    )

    timeline = subcommands.add_parser(
        "timeline",
        help="Show the unified server activity timeline.",
    )
    _add_store_args(timeline)
    timeline.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    show = subcommands.add_parser(
        "show",
        help="Show one revision with its parent diff, security verdict, and freshness.",
    )
    _add_store_args(show)
    show.add_argument(
        "revision",
        nargs="?",
        help="Revision ID; defaults to the latest discovery revision.",
    )
    show.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    check = subcommands.add_parser(
        "check",
        help="Show the immutable security verdict attached to a discovery revision.",
    )
    _add_store_args(check)
    check.add_argument(
        "--revision",
        help="Revision ID; defaults to the latest discovery revision.",
    )
    check.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    blame = subcommands.add_parser(
        "blame",
        help="Show which revision last changed each current tool field.",
    )
    _add_store_args(blame)
    blame.add_argument("--tool", required=True, help="Tool name.")
    blame.add_argument("--revision", help="Blame a historical revision instead of latest.")
    blame.add_argument(
        "--path",
        help="Only show this JSON-pointer path or descendants.",
    )
    blame.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    proxy = subcommands.add_parser(
        "proxy",
        help="Run a local MCP server behind DriftGuard's transparent stdio gate.",
    )
    _add_store_args(proxy)
    proxy.add_argument(
        "server_command",
        nargs=argparse.REMAINDER,
        help="Child MCP server command, usually after --.",
    )

    audit = subcommands.add_parser("audit", help="Inspect durable review history.")
    audit_sub = audit.add_subparsers(dest="audit_command", required=True)

    verify = audit_sub.add_parser("verify", help="Verify a tool review hash chain.")
    _add_store_args(verify)
    verify.add_argument("--tool", required=True, help="Tool name.")

    reviews = audit_sub.add_parser("reviews", help="Print review events for one tool.")
    _add_store_args(reviews)
    reviews.add_argument("--tool", required=True, help="Tool name.")

    return parser


def _run_benchmark(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if args.benchmark_name == "pairwise":
        report = evaluate_file(path)
    elif args.benchmark_name == "graph":
        report = evaluate_graph_file(path)
    else:
        report = evaluate_fusion_file(
            path,
            temporal_budget=args.temporal_budget,
        )
    print(report.model_dump_json(indent=2))
    return 0


def _current_status(
    store: SQLiteSnapshotStore,
    server_id: str,
) -> SurfaceObservation | None:
    revisions = store.revision_history(server_id)
    if not revisions:
        return None
    latest = revisions[-1]
    previous = revisions[-2] if len(revisions) > 1 else None
    return SurfaceObservation(
        revision=latest,
        previous_delta=diff_revisions(previous, latest) if previous is not None else None,
        trusted_status=compare_to_trusted(latest, store.trusted_tools(server_id)),
        freshness=catalog_freshness(
            store.catalog_signals(server_id),
            latest_revision_id=latest.revision_id,
        ),
    )


def _json_list(items) -> str:
    return "[\n" + ",\n".join(item.model_dump_json(indent=2) for item in items) + "\n]"


def _run_revision_command(args: argparse.Namespace) -> int:
    store = SQLiteSnapshotStore(args.db)
    try:
        if args.command == "freshness":
            latest = store.latest_revision(args.server)
            result = catalog_freshness(
                store.catalog_signals(args.server),
                latest_revision_id=latest.revision_id if latest is not None else None,
            )
            print(
                result.model_dump_json(indent=2)
                if args.json
                else render_catalog_freshness(result)
            )
            return 0

        if args.command == "log":
            revisions = store.revision_history(args.server)
            print(_json_list(revisions) if args.json else render_revision_log(revisions))
            return 0

        if args.command == "status":
            status = _current_status(store, args.server)
            if status is None:
                print("No revisions found.")
                return 1
            print(status.model_dump_json(indent=2) if args.json else render_surface_status(status))
            return 0

        if args.command == "timeline":
            result = build_server_timeline(
                revisions=store.revision_history(args.server),
                checks=store.revision_checks(args.server),
                signals=store.catalog_signals(args.server),
                reviews=store.server_reviews(args.server),
            )
            if args.json:
                print(_json_list(result))
            else:
                print(
                    "\n".join(render_timeline_event(item) for item in result)
                    or "No timeline events."
                )
            return 0

        if args.command == "show":
            revision_id = args.revision
            if revision_id is None:
                latest = store.latest_revision(args.server)
                if latest is None:
                    print("No revisions found.")
                    return 1
                revision_id = latest.revision_id

            revisions = store.revision_history(args.server)
            latest = revisions[-1] if revisions else None
            freshness = catalog_freshness(
                store.catalog_signals(args.server),
                latest_revision_id=latest.revision_id if latest is not None else None,
            )
            result = build_revision_view(
                revisions,
                target_revision_id=revision_id,
                security_check=store.get_revision_check(args.server, revision_id),
                freshness=freshness,
            )
            if result is None:
                print("Revision was not found.")
                return 1
            print(
                result.model_dump_json(indent=2)
                if args.json
                else render_revision_view(result)
            )
            return 0

        if args.command == "check":
            revision_id = args.revision
            if revision_id is None:
                latest = store.latest_revision(args.server)
                if latest is None:
                    print("No revisions found.")
                    return 1
                revision_id = latest.revision_id
            result = store.get_revision_check(args.server, revision_id)
            if result is None:
                print("Revision security check was not found.")
                return 1
            print(
                result.model_dump_json(indent=2)
                if args.json
                else render_revision_check(result)
            )
            return 0

        if args.command == "blame":
            result = blame_tool(
                store.revision_history(args.server),
                tool_name=args.tool,
                revision_id=args.revision,
                path_prefix=args.path,
            )
            if result is None:
                print("Tool or requested revision was not found.")
                return 1
            print(result.model_dump_json(indent=2) if args.json else render_tool_blame(result))
            return 0

        if args.command == "changes":
            feed = changes_after(store.revision_history(args.server), args.after)
            if feed is None:
                print("Unknown revision cursor.")
                return 1
            if args.json:
                print(_json_list(feed))
            else:
                print("\n".join(render_change_event(item) for item in feed) or "No new revisions.")
            return 0

        old = store.get_revision(args.server, args.from_revision)
        new = store.get_revision(args.server, args.to_revision)
        if old is None or new is None:
            print("One or both revisions were not found.")
            return 1
        delta = diff_revisions(old, new)
        print(delta.model_dump_json(indent=2) if args.json else render_revision_delta(delta))
        return 0
    finally:
        store.close()


def _run_watch(args: argparse.Namespace) -> int:
    cursor = args.after
    while True:
        store = SQLiteSnapshotStore(args.db)
        try:
            feed = changes_after(store.revision_history(args.server), cursor)
        finally:
            store.close()

        if feed is None:
            print("Unknown revision cursor.")
            return 1
        for event in feed:
            print(render_change_event(event), flush=True)
            cursor = event.revision_id
        time.sleep(max(0.1, args.interval))


def _run_audit(args: argparse.Namespace) -> int:
    store = SQLiteSnapshotStore(args.db)
    try:
        events = store.reviews(args.server, args.tool)
        if args.audit_command == "reviews":
            print(_json_list(events))
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
    if args.command in {
        "status",
        "freshness",
        "log",
        "diff",
        "changes",
        "timeline",
        "show",
        "check",
        "blame",
    }:
        return _run_revision_command(args)
    if args.command == "watch":
        return _run_watch(args)
    if args.command == "proxy":
        command = list(args.server_command)
        if command and command[0] == "--":
            command = command[1:]
        if not command:
            parser.error("proxy requires a child MCP server command after --")
        return run_stdio_proxy(
            command=command,
            db_path=args.db,
            server_id=args.server,
        )
    if args.command == "audit":
        return _run_audit(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
