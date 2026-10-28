"""Verify native bridge code with an isolated Python engine; optionally omit GUI wiring."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import venv
from pathlib import Path


def headless_project(root: Path, directory: Path, cargo: str) -> Path:
    """Keep production process helpers/tests unchanged; remove only Tauri wiring."""
    source = (root / "desktop/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    start = source.index("#[tauri::command]")
    tests = source.index("#[cfg(test)]", start)
    assert source.count("use tauri::Manager;\n") == 1
    body = source[:start].replace("use tauri::Manager;\n", "") + source[tests:]
    locked = tomllib.loads((root / "desktop/src-tauri/Cargo.lock").read_text())
    versions = {p["name"]: p["version"] for p in locked["package"]
                if p["name"] in {"serde_json", "tokio"}}
    manifest = tomllib.loads((root / "desktop/src-tauri/Cargo.toml").read_text())
    features = manifest["dependencies"]["tokio"]["features"]
    (directory / "src").mkdir()
    (directory / "src/lib.rs").write_text(body, encoding="utf-8")
    (directory / "Cargo.toml").write_text(
        '[package]\nname="driftguard-bridge-check"\nversion="0.0.0"\nedition="2021"\n'
        '[dependencies]\nserde_json=' + json.dumps("=" + versions["serde_json"]) + '\n'
        'tokio={version=' + json.dumps("=" + versions["tokio"]) + ',features='
        + json.dumps(features) + '}\n', encoding="utf-8",
    )
    target = directory / "Cargo.toml"
    # Retain production versions as the initial resolver input, then verify every
    # generated dependency against that lock before executing any Rust tests.
    shutil.copy2(root / "desktop/src-tauri/Cargo.lock", directory / "Cargo.lock")
    subprocess.run([cargo, "metadata", "--format-version", "1", "--manifest-path", str(target)],
                   cwd=root, stdout=subprocess.DEVNULL, check=True, timeout=180)
    generated = tomllib.loads((directory / "Cargo.lock").read_text())
    allowed = {(p["name"], p["version"], p.get("source"), p.get("checksum"))
               for p in locked["package"]}
    for package in generated["package"]:
        if package["name"] == "driftguard-bridge-check":
            continue
        identity = (package["name"], package["version"], package.get("source"),
                    package.get("checksum"))
        if identity not in allowed:
            raise RuntimeError("Headless dependency differs from production lock: " + package["name"])
    print(json.dumps({"scope": "Production bridge helpers/tests; excludes Tauri GUI wiring",
                      "production_sha256": hashlib.sha256(
                          (root / "desktop/src-tauri/src/lib.rs").read_bytes()).hexdigest(),
                      "headless_sha256": hashlib.sha256(body.encode()).hexdigest(),
                      "dependency_versions_match_production_lock": True}), flush=True)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headless", action="store_true",
                        help="Test identical process helpers without GTK/Tauri GUI dependencies")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    cargo = shutil.which("cargo")
    if cargo is None:
        print("Rust/Cargo is required for native bridge verification.", file=sys.stderr)
        return 1
    environment_root = root / "desktop/.venv-native"
    venv.EnvBuilder(with_pip=True).create(environment_root)
    # Keep this path: resolving a venv executable symlink loses its Python prefix.
    python = environment_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check", "-e", str(root),
         "-c", str(root / "requirements/core-constraints.txt")],
        cwd=root, check=True, timeout=300,
    )
    subprocess.run([str(python), "-I", "-c", "import driftguard.desktop_bridge"],
                   cwd=root, check=True, timeout=30)
    environment = dict(os.environ, DRIFTGUARD_TEST_PYTHON=str(python))
    with tempfile.TemporaryDirectory(prefix="driftguard-bridge-check-") as temporary:
        manifest = (headless_project(root, Path(temporary), cargo) if args.headless
                    else root / "desktop/src-tauri/Cargo.toml")
        if args.headless:
            environment["CARGO_TARGET_DIR"] = str(root / "desktop/src-tauri/target/headless-check")
        subprocess.run([cargo, "test", "--locked", "--manifest-path", str(manifest), "--lib",
                        "--", "--nocapture"],
                       cwd=root, env=environment, check=True, timeout=1200)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
