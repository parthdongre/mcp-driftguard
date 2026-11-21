# Windows description-change training

This is a local, research-only experiment for recognizing changes to advertised MCP tool permissions. It does not alter DriftGuard's enforcement path or install a model in the gateway.

## Reproduction

Run from the repository root in PowerShell. Keep the Python runtime, virtual environment, data, and model artifacts local to this checkout.

```powershell
$python = ".\.venv\Scripts\python.exe"
& $python experiments\windows_description_training\prepare.py --offline
& $python experiments\windows_description_training\train.py --smoke
& $python experiments\windows_description_training\train.py
& $python experiments\windows_description_training\evaluate.py
& $python experiments\windows_description_training\package.py
```

Use the exact setup and run commands recorded in `artifacts/windows-mcp-description-training/README_handoff.md` after the experiment completes. The setup pins the starting CUDA wheel at `torch==2.12.1` from the official `cu130` index. If this wheel cannot initialize CUDA on the installed driver, record the actual PyTorch matrix selection and versions in the run config before continuing.

## Pipeline

1. `prepare.py` checks the dated HISTOR manifest hashes, streams gzip JSONL, reconstructs old and new descriptions from `=`, `-`, and `+` chunks, labels only conservative observed cases, and separates non-description changes.
2. It deduplicates exact and reversed pairs, uses a conservative near-duplicate pass, applies a per-publisher cap, excludes CAPGATE repository families, and holds newer observations in a separate time challenge.
3. If high-confidence observed history does not meet the requested counts, it adds transparent fictional permission pairs. Each scenario family contains equivalent, narrower, broader, and genuinely ambiguous cases; the four cases stay together in the split. The generator runs consistency checks but these labels are not independent human judgments.
4. A frozen split index records row hashes and proves publisher, repository, definition-pair, near-duplicate, and template-family disjointness before training.
5. `train.py --smoke` uses 64 training rows to exercise the pinned encoder download, ordered tokenization, forward/backward, safetensors save, and checkpoint reload. Full training refuses to start unless that smoke run passes.
6. The full run reinitializes the three-label head and loads only pretrained base-encoder weights. It saves every epoch and selects the best epoch on provisional validation macro-F1. A TF-IDF logistic regression sees the same ordered before/after text pair.
7. `evaluate.py` compares both learned models with DriftGuard's existing description review heuristics, tunes expansion and unclear thresholds on validation only, and reports internal, time-challenge, and separate CAPGATE metrics.
8. `package.py` builds and verifies the requested ZIP. It includes the CC-BY HISTOR source files and attribution. CAPGATE text stays in the local cache because its rows quote several upstream repositories; the bundle includes the pinned source revision, record IDs, and description hashes instead.

## Labels and limits

The output labels are `same_or_narrower` (0), `broader` (1), and `unclear` (2). Unresolved history is kept in a review candidate file and never counted as training. The blinded queue omits labels and model scores. The main validation and test labels are provisional weak labels and controlled fictional labels; until independent human annotations are added, results must be reported as research-only. CAPGATE's published labels are rule-derived diagnostics, not human annotations.

The public CAPGATE checkout at the pinned revision did not contain `rust-version/build_description_corpus.py` or the earlier 142-pair DriftGuard subset. The experiment evaluates the published `real_benign` slice (144 rows) as the closest available separate benchmark and records this substitution. The user-provided starting counts (0/11 expansion recall and 15/131 benign false quarantines) are retained as reference metrics, not presented as a direct replay.

## Dependencies and GPU

`setup.ps1` installs a checkout-local Python 3.12, `.venv`, CUDA-enabled PyTorch, Transformers, Accelerate, Datasets, Hugging Face Hub, scikit-learn, safetensors, SentencePiece, joblib, and NumPy. The exact resolved versions, checkpoint SHA, driver, compute capability, and peak VRAM are saved with the run. The model is pinned to the Hugging Face commit SHA resolved at run start and loaded with `trust_remote_code=False` and safetensors.

## Files

- `prepare.py`: source checks, extraction, conservative labeling, controlled examples, deduplication, split freeze, and blinded review queue.
- `train.py`: CUDA smoke test, DeBERTa fit, and TF-IDF fit.
- `evaluate.py`: thresholds, metrics, predictions, and error reports.
- `package.py`: portable handoff ZIP and archive integrity verification.
- `WORK_JOURNAL.md`: execution notes and material deviations.
