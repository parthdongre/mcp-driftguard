from __future__ import annotations

import argparse
from pathlib import Path

from driftguard.dataset import write_jsonl
from driftguard.external_benchmarks import import_external_jsonl, validate_external_independence


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize an independently authored MCP security benchmark into DriftGuard pairs."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    records = import_external_jsonl(args.input)
    validate_external_independence(records)
    write_jsonl(args.output, records)
    print(f"Imported {len(records)} independent version pairs into {args.output}")


if __name__ == "__main__":
    main()
