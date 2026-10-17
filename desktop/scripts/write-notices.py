"""Preserve installed Python and selected native dependency attribution in packages."""
from __future__ import annotations

import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON_PACKAGES = ["mcp-driftguard", "pydantic", "pydantic-core", "annotated-types",
                   "typing-extensions", "typing-inspection", "jsonschema",
                   "jsonschema-specifications", "attrs", "referencing", "rpds-py",
                   "pyinstaller"]


def main() -> int:
    output = Path(sys.argv[1])
    sections = ["# MCP DriftGuard and bundled dependency notices",
                (ROOT / "LICENSE").read_text(encoding="utf-8")]
    for name in PYTHON_PACKAGES:
        distribution = importlib.metadata.distribution(name)
        sections.append(f"## Python: {name} {distribution.version}")
        sections.append("License metadata: " + str(
            distribution.metadata.get("License-Expression") or distribution.metadata.get("License") or "See upstream source"))
        for file in distribution.files or []:
            if any(Path(str(file)).name.upper().startswith(prefix)
                   for prefix in ("LICENSE", "COPYING", "COPYRIGHT")):
                path = Path(distribution.locate_file(file))
                if path.is_file() and path.stat().st_size <= 262144:
                    sections.append(path.read_text(encoding="utf-8", errors="replace"))
    for path in (Path(sys.base_prefix) / "LICENSE.txt",
                 Path(sys.base_prefix) / "lib" / ("python" + sys.version[:4]) / "LICENSE.txt"):
        if path.is_file():
            sections.extend(["## CPython runtime", path.read_text(encoding="utf-8", errors="replace")])
            break
    target = subprocess.check_output(["rustc", "-vV"], text=True).split("host: ", 1)[1].splitlines()[0]
    metadata = json.loads(subprocess.check_output([
        "cargo", "metadata", "--locked", "--format-version", "1",
        "--filter-platform", target, "--manifest-path",
        str(ROOT / "desktop/src-tauri/Cargo.toml")], text=True, cwd=ROOT))
    selected = {node["id"] for node in metadata["resolve"]["nodes"]}
    for package in metadata["packages"]:
        if package["id"] not in selected:
            continue
        sections.append(f"## Rust: {package['name']} {package['version']}")
        sections.append("License: " + str(package.get("license") or "See upstream source"))
        sections.append("Source: " + str(package.get("repository") or package.get("source") or "Local project"))
        directory = Path(package["manifest_path"]).parent
        licenses = {path for pattern in ("LICENSE*", "COPYING*", "COPYRIGHT*")
                    for path in directory.glob(pattern) if path.is_file()}
        if package.get("license_file"):
            path = directory / package["license_file"]
            if path.is_file():
                licenses.add(path)
        for path in sorted(licenses):
            if path.stat().st_size <= 262144:
                sections.append(path.read_text(encoding="utf-8", errors="replace"))
    output.write_text("\n\n".join(sections) + "\n", encoding="utf-8")
    print("Dependency notices written without changing upstream ownership.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
