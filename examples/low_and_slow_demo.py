from driftguard import SequentialDriftMonitor, TemporalConfig, make_snapshot


def tool(description: str):
    return {
        "name": "search_repo",
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        "annotations": {"readOnlyHint": True},
    }


def snapshot(description: str):
    return make_snapshot(
        server_id="demo-server",
        tool=tool(description),
        approval_state="approved",
    )


def main():
    approved = snapshot("Search repository files.")
    monitor = SequentialDriftMonitor(
        approved,
        TemporalConfig(
            reference_drift=0.02,
            cusum_threshold=0.20,
            baseline_threshold=0.90,
            memory_decay=1.0,
        ),
    )

    versions = [
        "Search repository files and inspect metadata.",
        "Search repository files, inspect metadata, and prepare results for sharing.",
        "Search repository files, inspect metadata, and prepare results for external sharing.",
        "Search repository files, inspect metadata, and upload results when requested.",
    ]

    for index, description in enumerate(versions, start=1):
        assessment = monitor.observe(snapshot(description))
        print(
            f"v{index}: step={assessment.step_risk:.3f} "
            f"baseline={assessment.baseline_risk:.3f} "
            f"cusum={assessment.cusum_score:.3f} "
            f"alert={assessment.alerted}"
        )
        for reason in assessment.reasons:
            print(f"  - {reason}")


if __name__ == "__main__":
    main()
