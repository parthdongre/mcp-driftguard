# Work journal

## 2026-11-21 — Windows description-pair research run

- Checked out public `Reda3D/mcp-driftguard` in the provided empty workspace. This repository has no `AGENTS.md`; the only nearby guidance belongs to a separate `AI-Workflow-Lab` repository and that checkout was left unchanged.
- Added an isolated experiment package under `experiments/windows_description_training/` and local output under `artifacts/windows-mcp-description-training/`. No enforcement code, policy, or gateway settings were changed.
- Retrieved the 2026-11-16 HISTOR manifest, `servers.jsonl.gz`, and `changes.jsonl.gz`; the verified SHA-256 hashes match the pinned manifest. No download substitutions were used. HISTOR identifies the snapshot as CC-BY-4.0.
- The public CAPGATE repository was pinned at `a7937dfdd2cea370bd5063307b635168c8429aba`; its `capgate_dataset.json` checksum is recorded in the source manifest. This checkout contains neither `rust-version/build_description_corpus.py` nor the older 142-pair subset. The published 144-row `real_benign` slice is used as the closest available separate diagnostic; its labels are rule-derived.
- Python 3.12 was absent on the laptop. Installed a checkout-local Python runtime through `uv`; the training environment is isolated in `.venv`.
- Experiment status, row counts, dependency versions, checkpoint revision, GPU telemetry, run failures/fixes, and archive verification are appended below after execution.
