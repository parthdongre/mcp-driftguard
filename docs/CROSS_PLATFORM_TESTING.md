# Verification and platform status

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
