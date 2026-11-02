# Verification and platform status

Current packaged implementation: **17 October 2026**, source revision
`1248ebc72075c2e55373cc80521d4870c2c18234`.
[Platform run 39057785978](https://github.com/parthdongre/mcp-driftguard/actions/runs/39057785978)
is the authoritative executed matrix for this code. Documentation-only followups
do not change those runtime sources.

| Check | macOS CI | Windows CI | Linux CI |
|---|---|---|---|
| Python correctness/security | 256 passed, 1 optional skip | 252 passed, 5 skips | 255 passed, 2 skips |
| Frontend logic / TypeScript / Vite | 9 logic tests and production build pass | 9 logic tests and production build pass | 9 logic tests and production build pass |
| Browser workflows | Executed in Linux browser job | Executed in Linux browser job | 23 checks; 6 sampled WCAG states, zero automated violations |
| Rust / actual Python bridge | 11 pass | 11 pass | 11 pass with full native wiring; 11 additional headless-helper checks pass |
| Optimized GLib backport regression | Not selected on this target | Not selected on this target | Forward/reverse/nth/last string iteration passes |
| Frozen packaged engine | Unicode import/review/approval/stale rejection/quarantine passes | Same | Same |
| Package validation | Bundled macOS app engine verified | NSIS install, installed engine and uninstall verified | Debian install, installed engine and removal verified |
| Real native startup | WebView launches; renderer initializes bundled Python/SQLite store | Same plus native window handle | Same plus visible Xvfb window using software compositing |
| Manual GUI / screen readers / high DPI | Not established | Not established | Not established |
| Signed production installation / updates | Not established | Not established | Not established |

The Linux extra skip is the native OS credential-store integration test because
an unlocked Secret Service session is not configured there. macOS and Windows
execute actual fixture-only credential create/read/update/delete checks. Windows
also skips four POSIX-specific permission/symlink checks. The optional XGBoost
path remains skipped. The frozen engine uses the constrained runtime versions;
the independent core workflow also checks the declared supported dependency range.

## What native startup establishes

The actual installed/bundled application launches its native WebView. Frontend
startup must invoke the real Rust command, launch the packaged Python engine and
initialize the real SQLite policy table. A compile or separately executed Python
helper alone cannot satisfy that assertion. Windows additionally requires a
nonzero window handle; Linux requires a visible titled window under Xvfb.

Linux's virtual-display launch uses a fresh D-Bus session, Openbox window manager,
explicit X11 backend and a 1600x1200 Xvfb screen. Bare Xvfb did not map/initialize
the window, so that incomplete desktop session was rejected rather than treated as
a passing platform check. The launch sets `WEBKIT_DISABLE_COMPOSITING_MODE=1`,
`WEBKIT_DISABLE_DMABUF_RENDERER=1` and `LIBGL_ALWAYS_SOFTWARE=1` for that CI process.
This is a headless-runner adaptation, not a change to normal product graphics
defaults. See [Tauri Linux graphics guidance](https://v2.tauri.app/develop/debug/linux-graphics/).
Hardware-specific display/driver behavior still needs target-machine testing.

These checks do not click through native controls, exercise native screen readers,
certify every OS version, test signed Gatekeeper/SmartScreen handling or prove
graceful recovery in every process/OS failure. Browser QA is separate: its
Python-backed test IPC stand-in does not claim native Rust IPC coverage.

## Review artifacts and provenance

The platform run retains unsigned per-platform preview packages for owner review.
macOS archives preserve bundle symlinks. Each artifact includes package SHA-256 and
the source revision; the separately retained engine manifest lists bundled file
hashes and build versions. Installed packages include dependency notices.
Artifacts are previews with 14-day retention, not a production release/update feed.

The fresh [native dependency run](https://github.com/parthdongre/mcp-driftguard/actions/runs/39056535860)
reports zero registry vulnerability entries/warnings and separately verifies the
exact local GLib backport. See [dependency findings](audit/DEPENDENCY_FINDINGS.md)
for why registry scanning is insufficient for locally patched source.

## Historical pre-packaging evidence

The following earlier verification record is preserved for traceability. Its
limitations describe those earlier revisions rather than overriding the current
packaged matrix above.


Current engineering followup: **17 October 2026**, code revision
`449bef11d20ae0e9a7a7321adbd2bea1c357b2cd`.
[Platform CI](https://github.com/parthdongre/mcp-driftguard/actions/runs/39051463275)
records actual runner results. Passing a native build or process-helper test does
not establish native window interaction, installation or publication accuracy.

| Check | Verified outcome | Boundary |
|---|---|---|
| Python full suite, local Linux / Python 3.12.14 | **218 passed, 1 skipped**, coverage **84.75%** (4340/5121 statements) | Optional XGBoost absent; no downloaded embedding models. Coverage run overlapped Rust tool builds; elapsed time is not a performance comparison. |
| Linux CI Python/UI | **218 passed, 1 skipped**; lint, 6 frontend tests and build passed | Source revision above |
| macOS CI Python/UI | **218 passed, 1 skipped**; lint, 6 frontend tests and build passed | Source revision above |
| Windows CI Python/UI | **214 passed, 5 skipped**; lint, 6 frontend tests and build passed | XGBoost plus four POSIX permissions/symlink checks skipped; Windows ACL behavior is not certified |
| Native process helpers, Linux | **11 Rust tests passed** locally and in CI with required isolated Python engine | Exact production helpers/tests, with only Tauri command/window wiring removed; all dependency identities match the production lock |
| macOS native Rust/Python and build | 11 native Rust/Python tests and unsigned no-bundle build passed | Actual native library code; no GUI startup/interaction or signed installation test |
| Windows native Rust/Python and build | 11 native Rust/Python tests and unsigned no-bundle build passed | No GUI startup/interaction or signed installation test |
| Source/test Ruff and Rust formatting | Passed | Static checks do not prove security |
| Linux full native build | Blocked at glib-sys by missing pkg-config/GTK-WebKit prerequisites locally | Headless process tests are not a substitute for GTK validation; dependency finding below blocks production release |
| Browser workflow, initial UI verification | **20 checks passed**, Chromium 141.0.7390.37 on Linux | Guided fixture plus Python/SQLite test IPC; browser UI source unchanged in this followup |
| Sampled accessibility, initial UI verification | Zero automated WCAG A/AA violations in **5 sampled states** | Native WebViews, manual VoiceOver/NVDA and all screens untested |
| Visual review, initial UI verification | Light overview/review/history, dark settings and 900px layout inspected | QA screenshots remain temporary |
| Reviewer CLI and Python wheel, initial verification | JSON parsed, controlled trace quarantined, wheel built | Controlled smoke checks, not accuracy/build reproducibility certification |
| Frozen corpus reproduction | **721/721 records exactly matched**, labels **0** | 494 primary +227 reference; upstream runtimes never executed; extractor source unchanged in this followup |
| Secret scan, 15 October | 71 candidates reviewed as hashes/authored test marker; 0 live secrets identified | Default scanner filters, no network verification/history/upstream/dependency scan; not absence proof |
| Python/npm advisory lookup, 15 October | No known entries in scoped runtime/npm graph | Dated lookup; independent supply-chain review pending |
| Rust audit, 17 October | 411 packages; 0 vulnerability-category entries, **1 unsound +1 unmaintained warning** | **Not clean**: Linux GTK path selects affected GLib/proc-macro-error. See audit/DEPENDENCY_FINDINGS.md. |

Initial evidence remains in `audit/final-*`, `audit/browser-check.json` and
`audit/verification-summary.json`. Followup evidence uses `audit/continuation-*`,
`audit/native-headless-*`, `audit/rust-dependency-*` and CI snapshots. The initial
Windows Python job was cancelled after hanging; it was never counted as a pass.
The followup source passes the Windows suite with bounded per-test diagnostics and
short adversarial parameter IDs. The evidence does not isolate one exclusive cause
for the original cancelled run.

## Reproduction

From the repository root:

```bash
python -m pip install -e '.[dev]' scikit-learn -c requirements/core-constraints.txt
python -m ruff check src tests desktop/scripts/check-native.py
python -m pytest -q --timeout=60 --timeout-method=thread -o faulthandler_timeout=30
python desktop/scripts/check-native.py --headless
# With native platform prerequisites, run actual Tauri library tests:
python desktop/scripts/check-native.py
```

The native runner requires Rust/Cargo, creates ignored `desktop/.venv-native`,
installs the constrained core, checks Python `-I` import and supplies a required
absolute venv executable to Rust tests. Headless mode rejects dependency identities
not in the production lock before tests run. It does not compile Tauri GUI wiring.

Frontend/browser checks, from `desktop/`:

```bash
npm ci
npm test
npm run build
npx playwright install chromium
npm run test:browser
cargo fmt --manifest-path src-tauri/Cargo.toml -- --check
npm run desktop:build -- --no-bundle
```

Browser tests self-host the built bundle. Their test-only IPC invokes actual
Python/SQLite, not native Rust IPC. Original Chromium download was unavailable;
that run selected installed Chromium via DRIFTGUARD_BROWSER_EXECUTABLE.

CI does not publish installers. Before release, verify native startup/shutdown,
file selection/downloads, engine failure, sleep/wake, high-DPI, keyboard/focus,
reduced motion, screen readers, installation/signing and updates on actual target
systems. Resolve the Linux dependency findings before a Linux production release.

### Executed preview artifacts

- [unsigned-desktop-preview-windows-latest](https://github.com/parthdongre/mcp-driftguard/actions/runs/39057785978/artifacts/12110560968) — artifact digest `sha256:d68f528ee756cde45355d3eabc23632316f504adee5392d0484ac870a0d0117c`
- [unsigned-desktop-preview-ubuntu-latest](https://github.com/parthdongre/mcp-driftguard/actions/runs/39057785978/artifacts/12110296761) — artifact digest `sha256:53f6850d5cc95559200aa0c9ffdca96558e1d65e830477092884835f358d352b`
- [unsigned-desktop-preview-macos-latest](https://github.com/parthdongre/mcp-driftguard/actions/runs/39057785978/artifacts/12109897372) — artifact digest `sha256:aa3faab63a5269f97a9fb802f4e8efe30f4fb19e789e8b198817014eb284b9c0`
