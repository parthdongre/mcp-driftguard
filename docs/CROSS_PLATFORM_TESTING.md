# Verification and platform status

These results apply to the current internal prototype. No native macOS/Windows
execution, signed installer or publication-grade accuracy is established here.

| Check | Verified outcome | Boundary |
|---|---|---|
| Python full suite, Linux / Python 3.12.14 | **217 passed, 1 skipped**, 35.60 s; coverage **84.80%** (4339/5117 statements) | Optional XGBoost absent; no downloaded embedding models |
| Source/test Ruff | Passed | Static lint does not prove security |
| Frontend logic | **6 tests passed** | Import/blinding/export/privacy/filtering/quarantine/stale decisions |
| TypeScript/Vite production build | Passed | Browser assets; not a native executable |
| Browser workflow | **20 checks passed**, Chromium 141.0.7390.37 on Linux | Isolated fixture plus actual Python/SQLite through test IPC |
| Sampled automated accessibility | Zero WCAG 2 A/AA and 2.1 AA violations in **5 sampled states** | Manual VoiceOver/NVDA, all screens and native WebViews untested |
| Screenshot visual review | Light overview/review/history, dark settings and 900px layout inspected | QA screenshots remain temporary |
| Installed reviewer CLI | JSON parsed and final scenario quarantined | Controlled demonstration |
| Python wheel | Built with `pip wheel . --no-deps --no-build-isolation` | Packaging smoke check; no bit-for-bit reproducibility certification |
| Rust formatting | `cargo fmt --check` passed | Native Rust tests/typecheck remain blocked |
| Linux native build | `cargo check` blocked at `glib-sys`: required `pkg-config`/GTK-WebKit build prerequisites unavailable | No native launch/build success claimed |
| macOS / Windows native build/run | Not executed here | CI prepared; no remote result yet |
| Frozen corpus reproduction | **721/721 records exactly matched**, labels 0 | 494 primary +227 reference; upstream runtimes never executed |
| Local secret scan | detect-secrets 1.5.0, no network verification; 71 candidates reviewed as hashes or authored test marker; 0 live secrets identified | Default scanner filters; no history/upstream/dependency scan; not proof of absence |
| Dependency advisory lookup | No known advisories for 10 pinned Python runtime packages or current npm lock graph | Dated lookup; Rust advisory/independent supply-chain review pending |

Initial browser contrast failures are archived in
`audit/browser-check-initial-failures.json`; current sampled states pass after
token corrections. npm audit identified Windows development-server advisories
in Vite 6.4.2; the dependency was upgraded to 6.4.4. Audit JSON, test XML, coverage,
environment and browser evidence are in `docs/audit/`.

## Reproduction

```bash
python -m pip install -e '.[dev]' scikit-learn -c requirements/core-constraints.txt
python -m ruff check src tests
python -m pytest -q --cov=driftguard
python desktop/scripts/generate-demo.py
cd desktop
npm ci
npm test
npm run build
npx playwright install chromium
npm run test:browser
cargo fmt --manifest-path src-tauri/Cargo.toml -- --check
npm run desktop:build -- --no-bundle
```

Browser tests self-host the built bundle on a temporary loopback port. Their IPC
stand-in invokes the actual Python bridge with a temporary database. It validates
renderer→Python→SQLite behavior, not native Rust IPC or OS packaging. Chromium
download was unavailable here; the recorded run used installed Chromium 141 via
`DRIFTGUARD_BROWSER_EXECUTABLE`.

`.github/workflows/desktop-validation.yml` prepares Python/UI jobs on Linux,
macOS and Windows, plus unsigned no-bundle native builds on macOS/Windows. It
does not publish installers. Run and inspect it after authorized branch publication.

Before release, test native startup/shutdown, paths, file selection/downloads,
engine failure, connection loss, sleep/wake, long catalogs, high-DPI scaling,
keyboard/focus, reduced motion, screen readers, installation/signing and updates
on actual target platforms.
