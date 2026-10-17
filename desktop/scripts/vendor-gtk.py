"""Vendor checksum-verified GTK compatibility sources and apply narrow documented fixes.

This preparation script is separate from application execution. Third-party MIT
licenses and source are preserved in the generated third_party directory.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESTINATION = ROOT / "desktop/src-tauri/third_party"
CRATES = {
    "glib": ("0.18.5", "233daaf6e83ae6a12a52055f568f9d7cf4671dabb78ff9560ab6da230ce00ee5"),
    "glib-macros": ("0.18.5", "0bb0228f477c0900c880fd78c8759b95c7636dbd7842707f49e132378aa2acdc"),
    "gtk3-macros": ("0.18.2", "52ff3c5b21f14f0736fed6dcfc0bfb4225ebf5725f3c0209edeec181e4d73e9d"),
}


def main() -> int:
    if DESTINATION.exists():
        raise RuntimeError("Refusing to overwrite existing dependency sources")
    DESTINATION.mkdir()
    for name, (version, digest) in CRATES.items():
        url = f"https://static.crates.io/crates/{name}/{name}-{version}.crate"
        with urllib.request.urlopen(url, timeout=30) as response:
            archive = response.read(8 * 1024 * 1024 + 1)
        if len(archive) > 8 * 1024 * 1024 or hashlib.sha256(archive).hexdigest() != digest:
            raise RuntimeError("Dependency archive checksum or byte limit failed: " + name)
        prefix = name + "-" + version
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as source:
            members = source.getmembers()
            if len(members) > 2000 or sum(member.size for member in members) > 32 * 1024 * 1024:
                raise RuntimeError("Dependency extraction limit failed")
            for member in members:
                path = Path(member.name)
                if (path.is_absolute() or ".." in path.parts or not path.parts
                        or path.parts[0] != prefix or not (member.isfile() or member.isdir())):
                    raise RuntimeError("Unsafe dependency archive member")
                if member.isfile():
                    output = DESTINATION / name / Path(*path.parts[1:])
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(source.extractfile(member).read())
    variant = DESTINATION / "glib/src/variant_iter.rs"
    source = variant.read_text(encoding="utf-8")
    old = "let p: *mut libc::c_char = std::ptr::null_mut();"
    pointer = "\n                &p,"
    if source.count(old) != 1 or source.count(pointer) != 1:
        raise RuntimeError("GLib patch context differs from the reviewed upstream fix")
    variant.write_text(source.replace(old, old.replace("let p:", "let mut p:"))
                       .replace(pointer, "\n                &mut p,"), encoding="utf-8")
    for name in ("glib-macros", "gtk3-macros"):
        manifest = DESTINATION / name / "Cargo.toml"
        source = manifest.read_text(encoding="utf-8")
        source, count = re.subn(
            r'(\[dependencies\.proc-macro-error\]\n)version = "[^"]+"',
            r'\g<1>package = "proc-macro-error2"\nversion = "=2.0.1"', source)
        if count != 1:
            raise RuntimeError("Macro maintenance replacement context differs")
        manifest.write_text(source, encoding="utf-8")
    provenance = {
        "archive_checksums": {name: {"version": version, "sha256": checksum}
                              for name, (version, checksum) in CRATES.items()},
        "glib_fix": "https://github.com/gtk-rs/gtk-rs-core/commit/b5a4071e439bef2b5eea76c3aa25e5ae84839e34",
        "glib_advisory": "RUSTSEC-2024-0429",
        "macro_change": "Rename maintained proc-macro-error2 2.0.1 to the existing import name",
        "status": "Compatibility backport; requires optimized regression and native platform tests",
    }
    (DESTINATION / "PROVENANCE.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    (DESTINATION / "README.md").write_text(
        "# GTK compatibility sources\n\n"
        "These MIT-licensed upstream crates retain their individual licenses and ownership.\n"
        "The GLib change exactly backports upstream commit b5a4071e439bef2b5eea76c3aa25e5ae84839e34.\n"
        "The two macro manifests replace unmaintained proc-macro-error with the maintained\n"
        "proc-macro-error2 2.0.1 under the same Rust import name. No other source is changed.\n"
        "PROVENANCE.json records original archive checksums. Reproduce from an empty\n"
        "third_party directory using desktop/scripts/vendor-gtk.py.\n", encoding="utf-8")
    manifest = ROOT / "desktop/src-tauri/Cargo.toml"
    source = manifest.read_text(encoding="utf-8")
    if "[patch.crates-io]" in source:
        raise RuntimeError("Review existing crate patches before adding these overrides")
    source += '\n[patch.crates-io]\n'
    source += '\n'.join(f'{name} = {{ path = "third_party/{name}" }}' for name in CRATES) + '\n'
    source += '\n[target.\'cfg(target_os = "linux")\'.dev-dependencies]\nglib = "=0.18.5"\n'
    manifest.write_text(source, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
