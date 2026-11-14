# Native dependency findings — 17 October 2026

The initial scan found GLib unsoundness and an obsolete macro helper. The current
compatibility sources and lockfile address those paths explicitly; raw historical
evidence is retained below rather than overwritten.

## Current compatibility-source evidence

[Native dependency workflow 39056535860](https://github.com/parthdongre/mcp-driftguard/actions/runs/39056535860)
uses `cargo-audit 0.22.2` and RustSec database commit
`999ec89d5d3f10f20be14750ec8c2d8b44e0ac9b` (1338 advisories). It reports
**0 vulnerability entries and 0 warnings** for the revised lockfile.

This requires qualification: GLib 0.18.5 is now a local path patch, so the registry
version scan alone is insufficient evidence. The audit separately verifies the
exact upstream mutable out-pointer backport, while optimized native regression
tests exercise forward/backward string iteration. Third-party sources retain their
licenses, original archive checksums and narrow change provenance.

| Original finding | Implemented resolution |
|---|---|
| RUSTSEC-2024-0429, GLib VariantStrIter unsoundness | Exact upstream fix b5a4071e439bef2b5eea76c3aa25e5ae84839e34 backported to the compatible 0.18.5 source |
| RUSTSEC-2024-0370, unmaintained proc-macro-error 1 | Remove the helper from the lock; the two macro crates use proc-macro-error3 3.1.1 with explicit syn2-error compatibility |
| RUSTSEC-2026-0173, unmaintained proc-macro-error2 | Fresh audit rejected the initially proposed replacement; version 2 is absent from the final lock |

The macro root aliases account for the maintained helper's generated absolute
crate paths. `third_party/PROVENANCE.json` and
`desktop/scripts/vendor-gtk.py` record/reproduce the compatibility source changes.
The official fork metadata and exact crates.io index checksums were checked before
selecting 3.1.1; no blanket advisory ignore was added.

The raw scan and interpreted summary are retained as workflow artifacts.
The committed [current summary](rust-dependency-followup.json) records the counts,
database revision and explicit lack of an independent audit. Neither a zero-count
lockfile scan nor these tests establish whole-product safety, signing, installation
compatibility on every distribution, or independent security certification.

## Historical initial scan

The following records describe the original registry-only lockfile before the
compatibility changes and are retained for audit history:

- [Initial raw audit](rust-dependency-audit.json): zero vulnerability-category
  entries, GLib unsoundness warning and proc-macro-error maintenance warning.
- [Initial target dependency paths](rust-dependency-paths.json): both original
  dependencies selected for Linux, not macOS/Windows.
- An intermediate fresh scan additionally identified RUSTSEC-2026-0173 in
  proc-macro-error2; that candidate was replaced, not suppressed.

Reproduce the current scan:

```bash
cargo install cargo-audit --version 0.22.2 --locked
python desktop/scripts/audit-native.py
```

Recheck the advisory database before production release. Native GUI/manual
accessibility validation, signing, update trust and independent security review
remain separate requirements.
