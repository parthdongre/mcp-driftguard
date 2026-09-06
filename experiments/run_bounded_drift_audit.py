from __future__ import annotations

import argparse
import json
from pathlib import Path

from driftguard.bounded_drift import LocalDriftBudget, analyze_bounded_trajectory
from driftguard.dataset import read_trajectory_jsonl
from driftguard.mutations import build_low_and_slow_trajectory


def _demo_trajectory():
    tool = {
        "name": "search_documents",
        "description": "Search selected project documents and return matching excerpts.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    }
    return build_low_and_slow_trajectory(
        repository_id="controlled/demo",
        server_id="controlled-demo",
        tool=tool,
        trajectory_id="controlled-low-and-slow-demo",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit whether trajectories satisfy an explicit local low-and-slow drift budget."
    )
    parser.add_argument("--input", type=Path, help="Optional trajectory JSONL")
    parser.add_argument("--max-risk", type=float, default=0.35)
    parser.add_argument("--max-lexical", type=float, default=0.45)
    parser.add_argument("--max-capability", type=float, default=0.35)
    parser.add_argument("--max-structural-events", type=int, default=4)
    parser.add_argument("--max-sensitive", type=int, default=1)
    parser.add_argument("--max-urls", type=int, default=1)
    args = parser.parse_args()

    budget = LocalDriftBudget(
        max_risk_signal=args.max_risk,
        max_lexical_change_ratio=args.max_lexical,
        max_capability_escalation=args.max_capability,
        max_structural_events=args.max_structural_events,
        max_sensitive_terms_added=args.max_sensitive,
        max_urls_added=args.max_urls,
    )
    trajectories = read_trajectory_jsonl(args.input) if args.input else [_demo_trajectory()]
    reports = [analyze_bounded_trajectory(trajectory, budget=budget) for trajectory in trajectories]

    payload = {
        "budget": budget.__dict__,
        "trajectories": len(reports),
        "qualified_bounded_rug_pulls": sum(
            report.all_local_steps_within_budget and report.endpoint_exceeds_local_budget
            for report in reports
        ),
        "reports": [
            {
                "trajectory_id": report.trajectory_id,
                "all_local_steps_within_budget": report.all_local_steps_within_budget,
                "approved_to_final_risk": report.approved_to_final_risk,
                "approved_to_final_capability_escalation": (
                    report.approved_to_final_capability_escalation
                ),
                "endpoint_exceeds_local_budget": report.endpoint_exceeds_local_budget,
                "steps": [step.__dict__ for step in report.steps],
            }
            for report in reports
        ],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
