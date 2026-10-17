"""Launch the actual packaged WebView and verify its real Python/SQLite startup.

This proves window/process startup and renderer-triggered engine initialization,
not manual interaction, screen-reader behavior or visual layout.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

IDENTIFIER = "io.driftguard.desktop"


def main() -> int:
    executable = Path(sys.argv[1])
    if sys.platform == "darwin":
        directory = Path.home() / "Library/Application Support" / IDENTIFIER
    elif os.name == "nt":
        directory = Path(os.environ["APPDATA"]) / IDENTIFIER
    else:
        directory = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / IDENTIFIER
    database = directory / "guard.sqlite3"
    if database.exists():
        raise RuntimeError("Native startup verification requires a fresh disposable runner store")
    process = subprocess.Popen([str(executable)], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL,
                               env={key: value for key, value in os.environ.items()
                                    if key not in {"DRIFTGUARD_PYTHON", "PYTHONHOME", "PYTHONPATH"}})
    try:
        deadline = time.monotonic() + 30
        initialized = False
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Packaged native window exited before engine startup")
            if database.is_file():
                try:
                    with sqlite3.connect("file:" + database.as_posix() + "?mode=ro", uri=True) as db:
                        initialized = db.execute("SELECT value FROM guard_meta WHERE key='policy'").fetchone() is not None
                except sqlite3.Error:
                    initialized = False
                if initialized:
                    break
            time.sleep(0.2)
        if not initialized:
            raise RuntimeError("Native renderer did not initialize the bundled Python review store")
        if sys.platform.startswith("linux"):
            window = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", "MCP DriftGuard"],
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5)
            if window.returncode != 0 or not window.stdout.strip():
                raise RuntimeError("The Linux native window was not visible under Xvfb")
        elif os.name == "nt":
            check = subprocess.run(["powershell", "-NoProfile", "-Command",
                f"(Get-Process -Id {process.pid}).MainWindowHandle"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, text=True)
            if check.returncode != 0 or check.stdout.strip() == "0" or not check.stdout.strip():
                raise RuntimeError("The Windows native window handle was unavailable")
        print("Actual packaged WebView startup and renderer-to-engine SQLite initialization passed.")
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
