"""Launch the actual packaged WebView and verify its real Python/SQLite startup.

This proves window/process startup and renderer-triggered engine initialization,
not manual interaction, screen-reader behavior or visual layout.
"""
from __future__ import annotations

import base64
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

IDENTIFIER = "io.driftguard.desktop"


def wait_for_windows_window(process: subprocess.Popen, timeout: float = 15) -> None:
    from ctypes import WINFUNCTYPE, WinDLL, byref, wintypes

    user32 = WinDLL("user32", use_last_error=True)
    callback_type = WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, wintypes.LPDWORD]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    found = False

    @callback_type
    def visit(window, _):
        nonlocal found
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, byref(owner))
        if (owner.value == process.pid and user32.IsWindowVisible(window)
                and user32.GetWindowTextLengthW(window) > 0):
            found = True
            return False
        return True

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and process.poll() is None:
        user32.EnumWindows(visit, 0)
        if found:
            return
        time.sleep(0.2)
    raise RuntimeError("The Windows native window was not visible after startup")


def main() -> int:
    executable = Path(sys.argv[1])
    rust = "--rust" in sys.argv[2:]
    identifier = IDENTIFIER + ".rust" if rust else IDENTIFIER
    with (tempfile.TemporaryDirectory(prefix="driftguard-native-startup-") as isolated,
          tempfile.TemporaryFile() as diagnostics):
        environment = dict(os.environ)
        if sys.platform.startswith("linux"):
            environment["XDG_DATA_HOME"] = str(Path(isolated) / "data")
        if sys.platform == "darwin":
            directory = Path.home() / "Library/Application Support" / identifier
        elif os.name == "nt":
            directory = Path(os.environ["APPDATA"]) / identifier
        else:
            directory = Path(environment["XDG_DATA_HOME"]) / identifier
        database = directory / ("guard-rust.sqlite3" if rust else "guard.sqlite3")
        if database.exists():
            raise RuntimeError("Native startup verification requires a fresh disposable runner store")
        manager = None
        if sys.platform.startswith("linux"):
            manager = subprocess.Popen(["openbox", "--sm-disable"], stdout=subprocess.DEVNULL,
                                       stderr=diagnostics, env=environment)
            time.sleep(0.5)
        process = subprocess.Popen([str(executable)], stdout=subprocess.DEVNULL,
                                   stderr=diagnostics,
                                   env={key: value for key, value in environment.items()
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
                            query = ("SELECT cursor FROM alerts WHERE id=1" if rust else
                                     "SELECT value FROM guard_meta WHERE key='policy'")
                            initialized = db.execute(query).fetchone() is not None
                    except sqlite3.Error:
                        initialized = False
                    if initialized:
                        break
                time.sleep(0.2)
            if not initialized:
                raise RuntimeError("Native renderer did not initialize the bundled review store")
            if sys.platform.startswith("linux"):
                window = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", "MCP DriftGuard"],
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, check=False)
                if window.returncode != 0 or not window.stdout.strip():
                    raise RuntimeError("The Linux native window was not visible under Xvfb")
            elif os.name == "nt":
                wait_for_windows_window(process)
            print("Actual packaged WebView startup and renderer-to-engine SQLite initialization passed.")
        except BaseException:
            print(f"Startup state directory exists: {directory.is_dir()}; database exists: {database.is_file()}", file=sys.stderr)
            if sys.platform.startswith("linux"):
                listing = subprocess.run(["xwininfo", "-root", "-tree"], stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, timeout=5, check=False)
                print("Native X11 window tree:", listing.stdout[:8192].decode("utf-8", errors="replace"),
                      file=sys.stderr)
                screenshot = subprocess.run(
                    ["import", "-window", "root", "-resize", "1000x700", "png:-"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, check=False)
                if screenshot.returncode == 0 and len(screenshot.stdout) <= 4 * 1024 * 1024:
                    print("DRIFTGUARD_NATIVE_SCREENSHOT=" + base64.b64encode(screenshot.stdout).decode())
            diagnostics.seek(0)
            print("Native startup diagnostics (fresh, empty disposable runner only):",
                  diagnostics.read(4096).decode("utf-8", errors="replace"), file=sys.stderr)
            raise
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            if manager is not None:
                manager.terminate()
                try:
                    manager.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    manager.kill()
                    manager.wait(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
