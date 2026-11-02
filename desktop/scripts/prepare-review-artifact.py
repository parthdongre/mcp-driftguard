"""Archive unsigned review packages, preserving macOS bundle symlinks."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUNDLES = ROOT / "desktop/src-tauri/target/release/bundle"


def main() -> int:
    output = ROOT / "desktop/build/review"
    output.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        app, = BUNDLES.glob("macos/*.app")
        destination = output / "MCP-DriftGuard-macOS-arm64-unsigned-preview.zip"
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                        str(app), str(destination)], check=True, timeout=120)
    else:
        candidates = BUNDLES.glob("nsis/*.exe" if os.name == "nt" else "deb/*.deb")
        package, = candidates
        destination = output / package.name
        shutil.copy2(package, destination)
    manifest = {"source_revision": os.environ.get("GITHUB_SHA"), "unsigned_preview": True,
                "manual_native_interaction_verified": False,
                "package": destination.name,
                "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}
    (output / "package-provenance.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
