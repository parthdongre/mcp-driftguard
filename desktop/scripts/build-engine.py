"""Build a platform-native, pinned Python engine and verify its actual executable."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "desktop/build/engine"
NAME = "driftguard-engine"


def exchange(engine: Path, db: Path, request: dict) -> dict:
    completed = subprocess.run(
        [str(engine), "bridge", "--db", str(db)],
        input=json.dumps(request, ensure_ascii=False).encode("utf-8"),
        capture_output=True, timeout=30, check=False,
        # Frozen execution must not depend on an inherited Python installation.
        env={key: value for key, value in os.environ.items()
             if key not in {"PYTHONPATH", "PYTHONHOME", "DRIFTGUARD_PYTHON"}},
    )
    if len(completed.stdout) > 16 * 1024 * 1024:
        raise RuntimeError("Frozen response exceeds the protocol limit")
    response = json.loads(completed.stdout)
    expected = 0 if response.get("ok") is True else 1
    if completed.returncode != expected:
        raise RuntimeError("Frozen response and exit status disagree")
    return response


def verify(engine: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="driftguard packaged revisión 测试 ") as directory:
        db = Path(directory) / "guard.sqlite3"
        assert exchange(engine, db, {"action": "overview"})["data"]["tools"] == 0
        imported = exchange(engine, db, {
            "action": "import_definitions", "server_id": "packaged-test",
            "identity": "packaged-fixture", "tools": [{
                "name": "read_notes", "description": "Read résumé — 测试 🌙",
                "inputSchema": {"type": "object", "properties": {}},
            }],
        })
        assert imported["ok"], imported
        tool = imported["data"][0]
        identity = {"server_id": tool["server_id"], "tool_name": tool["tool_name"]}
        reviewed = exchange(engine, db, {"action": "review", **identity})
        assert reviewed["data"]["new_tool"]["description"] == "Read résumé — 测试 🌙"
        decision = {"action": "approve", **identity, "expected_sha256": tool["sha256"],
                    "expected_revision": tool["revision"]}
        approved = exchange(engine, db, decision)
        assert approved["ok"] and approved["data"]["status"] == "approved"
        assert exchange(engine, db, decision)["ok"] is False
        current = approved["data"]
        quarantined = exchange(engine, db, {
            "action": "quarantine", **identity, "expected_sha256": current["sha256"],
            "expected_revision": current["revision"],
        })
        assert quarantined["data"]["status"] == "quarantined"
        current = quarantined["data"]
        assert exchange(engine, db, {
            "action": "approve", **identity, "expected_sha256": current["sha256"],
            "expected_revision": current["revision"],
        })["ok"] is False
        assert exchange(engine, db, {"action": "activity"})["data"]
        host = exchange(engine, db, {"action": "host_catalog_import", "source": {
            "source_id": "packaged-host", "name": "Hosted metadata fixture",
            "description": "Names and descriptions only", "captured_at": "2026-10-28",
            "visibility": "session_tools", "tools": [{
                "name": "inspect", "description": "Read a selected design",
            }],
        }})
        assert host["ok"] and host["data"]["tools_count"] == 1
        assert exchange(engine, db, {"action": "host_catalog_list"})["data"][0]["name"] == "Hosted metadata fixture"
        rejected = exchange(engine, db, {"action": "shell", "command": "unused"})
        assert rejected["ok"] is False
    gateway = subprocess.run([str(engine), "gateway", "--help"],
                             capture_output=True, timeout=30, check=False)
    assert gateway.returncode == 0 and b"--config" in gateway.stdout


def main() -> int:
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
         "--name", NAME, "--distpath", str(OUTPUT),
         "--workpath", str(ROOT / "desktop/build/pyinstaller"),
         "--specpath", str(ROOT / "desktop/build"),
         "--paths", str(ROOT / "src"),
         "--collect-all", "jsonschema_specifications",
         "--collect-all", "pydantic",
         "--hidden-import", "pydantic_core",
         str(ROOT / "desktop/scripts/engine-entry.py")],
        cwd=ROOT, check=True, timeout=600,
    )
    engine = OUTPUT / NAME / (NAME + (".exe" if os.name == "nt" else ""))
    verify(engine)
    subprocess.run([sys.executable, str(ROOT / "desktop/scripts/write-notices.py"),
                    str(engine.parent / "THIRD_PARTY_NOTICES.md")],
                   cwd=ROOT, check=True, timeout=180)
    files = {}
    for path in sorted(engine.parent.rglob("*")):
        if path.is_file():
            files[path.relative_to(engine.parent).as_posix()] = hashlib.sha256(
                path.read_bytes()).hexdigest()
    manifest = {"schema_version": 1, "platform": platform.platform(),
                "machine": platform.machine(), "python": platform.python_version(),
                "engine_version": "0.4.0", "pyinstaller_version": "6.22.3",
                "source_revision": os.environ.get("GITHUB_SHA"),
                "verification": "actual frozen Unicode review, approval, stale rejection, quarantine",
                "files_sha256": files}
    (OUTPUT / "engine-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"engine": str(engine), "verified": True, "files": len(files)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
