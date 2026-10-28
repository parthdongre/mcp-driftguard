"""Fixed entry point for the bundled engine; no renderer-selected module loading."""
from __future__ import annotations

import sys

from driftguard import credentials, desktop_bridge, gateway_cli


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in {"bridge", "gateway", "credentials"}:
        print("Expected bridge, gateway or credentials", file=sys.stderr)
        return 2
    action, arguments = sys.argv[1], sys.argv[2:]
    commands = {"bridge": desktop_bridge.main, "gateway": gateway_cli.main,
                "credentials": credentials.main}
    return commands[action](arguments)


if __name__ == "__main__":
    raise SystemExit(main())
