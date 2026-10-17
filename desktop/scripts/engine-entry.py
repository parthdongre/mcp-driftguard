"""Fixed entry point for the bundled engine; no renderer-selected module loading."""
from __future__ import annotations

import sys

from driftguard import desktop_bridge, gateway_cli


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in {"bridge", "gateway"}:
        print("Expected bridge or gateway", file=sys.stderr)
        return 2
    action, arguments = sys.argv[1], sys.argv[2:]
    return (desktop_bridge.main(arguments) if action == "bridge"
            else gateway_cli.main(arguments))


if __name__ == "__main__":
    raise SystemExit(main())
