# Native dependency findings — 17 October 2026

`cargo-audit 0.22.2` inspected **411** packages in the production Cargo.lock against
RustSec database commit `999ec89d5d3f10f20be14750ec8c2d8b44e0ac9b`
(1338 advisories; last update 2026-10-17T17:23:59+02:00).

The tool reports **0 vulnerability-category entries**, **1 unsoundness warning**
and **1 unmaintained warning**. This is **not a clean audit**. Raw results are in
[rust-dependency-audit.json](rust-dependency-audit.json).

| Finding | Locked dependency and path | Decision |
|---|---|---|
| [RUSTSEC-2024-0429](https://rustsec.org/advisories/RUSTSEC-2024-0429.html): unsound VariantStrIter iteration | glib 0.18.5 through the Linux GTK/WebKit/Tauri stack | Linux native production release remains blocked pending a compatible reviewed fix. RustSec lists >=0.20.0 patched; GTK 0.18 currently requires the 0.18 line, so a direct version override is not a validated solution. |
| [RUSTSEC-2024-0370](https://rustsec.org/advisories/RUSTSEC-2024-0370.html): unmaintained proc-macro-error | proc-macro-error 1.0.4 through Linux glib-macros/gtk3-macros | Retain the maintenance finding; replace through a compatible upstream dependency path or reviewed backport before release. No blanket ignore was added. |

`cargo tree --locked -i PACKAGE --target TARGET` selects both dependencies for
`x86_64-unknown-linux-gnu` and neither for `aarch64-apple-darwin` or
`x86_64-pc-windows-msvc`. Exact commands and trees are in
[rust-dependency-paths.json](rust-dependency-paths.json). This establishes target
dependency selection, not whether an affected function is reachable from an
untrusted input. No exploit-reachability or whole-product safety claim follows.

The Linux headless bridge tests omit GUI wiring and select only the process
helper dependencies; they do not exercise or certify GTK. macOS/Windows builds
and tests are likewise not a substitute for independent security review, native
GUI validation, signing, installation or secure updates.

Reproduce from the repository root:

```bash
cargo install cargo-audit --version 0.22.2 --locked
cargo audit --file desktop/src-tauri/Cargo.lock --json
cargo tree --locked --manifest-path desktop/src-tauri/Cargo.toml -i glib@0.18.5 --target x86_64-unknown-linux-gnu
```

Advisory lookup is dated evidence. Recheck the current database before release;
retain warnings even when the tool's default exit status is zero.
