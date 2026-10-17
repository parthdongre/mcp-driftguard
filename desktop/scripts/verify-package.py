"""Verify the runtime from a macOS bundle or an actually installed Windows package."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("build_engine", ROOT / "desktop/scripts/build-engine.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def main() -> int:
    bundles = ROOT / "desktop/src-tauri/target/release/bundle"
    if os.name == "nt":
        installer, = bundles.glob("nsis/*.exe")
        with tempfile.TemporaryDirectory(prefix="driftguard-install-check-") as temporary:
            destination = Path(temporary) / "installed"
            subprocess.run([str(installer), "/S", "/D=" + str(destination)],
                           check=True, timeout=120)
            try:
                engine = destination / "engine/driftguard-engine.exe"
                assert engine.is_file(), "Installed engine was not found"
                builder.verify(engine)
                assert (destination / "driftguard-desktop.exe").is_file()
            finally:
                uninstallers = list(destination.glob("*ninstall*.exe"))
                if uninstallers:
                    subprocess.run([str(uninstallers[0]), "/S"],
                                   check=True, timeout=120)
    else:
        app, = bundles.glob("macos/*.app")
        engine = app / "Contents/Resources/engine/driftguard-engine"
        assert engine.is_file(), "Bundled engine was not found"
        builder.verify(engine)
        assert (app / "Contents/Info.plist").is_file()
    print("Packaged runtime, Unicode state and review decisions verified.")
    print("This check does not claim GUI interaction, signing or notarization.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
