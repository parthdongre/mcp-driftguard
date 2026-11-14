"""Retain raw RustSec evidence and distinguish the exact reviewed GLib backport."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    output = ROOT / "desktop/build/security"
    output.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["cargo", "audit", "--file",
                             str(ROOT / "desktop/src-tauri/Cargo.lock"), "--json"],
                            cwd=ROOT, capture_output=True, timeout=300, check=False)
    (output / "rustsec-raw.json").write_bytes(result.stdout)
    stderr = result.stderr.decode("utf-8", errors="replace").strip()
    # cargo audit exits 1 when it finds vulnerabilities; anything else is a tool failure.
    if result.returncode not in {0, 1}:
        print(f"cargo audit failed with exit status {result.returncode}: {stderr}", file=sys.stderr)
        return 1
    try:
        audit = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        print(f"cargo audit did not produce valid JSON ({error}): {stderr}", file=sys.stderr)
        return 1
    if not isinstance(audit, dict):
        print("cargo audit JSON output was not an object", file=sys.stderr)
        return 1
    variant = (ROOT / "desktop/src-tauri/third_party/glib/src/variant_iter.rs").read_text()
    backport = ("let mut p: *mut libc::c_char = std::ptr::null_mut();" in variant
                and "\n                &mut p," in variant
                and "\n                &p," not in variant)
    lock = (ROOT / "desktop/src-tauri/Cargo.lock").read_text()
    obsolete_macro_absent = ('name = "proc-macro-error"' not in lock
                             and 'name = "proc-macro-error2"' not in lock)
    vulnerabilities = audit.get("vulnerabilities", {}).get("list", [])
    unresolved = []
    warnings = []
    for category, entries in audit.get("warnings", {}).items():
        for entry in entries:
            finding = entry.get("advisory", {})
            package = entry.get("package", {})
            ident = finding.get("id")
            row = {"category": category, "id": ident,
                   "package": package.get("name"), "version": package.get("version")}
            warnings.append(row)
            if not (ident == "RUSTSEC-2024-0429" and package.get("name") == "glib"
                    and package.get("version") == "0.18.5" and backport):
                unresolved.append(row)
    summary = {"vulnerability_count": len(vulnerabilities),
               "raw_warnings": warnings, "unresolved_warnings": unresolved,
               "exact_upstream_glib_out_pointer_backport_present": backport,
               "unmaintained_proc_macro_error_absent": obsolete_macro_absent,
               "upstream_fix": "b5a4071e439bef2b5eea76c3aa25e5ae84839e34",
               "independent_security_audit_completed": False,
               "database": audit.get("database"),
               "scope": "Dated Cargo.lock scan and exact local compatibility-source verification"}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("DRIFTGUARD_AUDIT_SUMMARY=" + json.dumps(summary, separators=(",", ":")))
    if (result.returncode not in {0, 1} or vulnerabilities or unresolved
            or not backport or not obsolete_macro_absent):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
