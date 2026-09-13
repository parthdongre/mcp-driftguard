# MCP DriftGuard build notes

This file is a concise engineering map of the major repository decisions. It is intentionally an overview, not line-by-line documentation.

## 1. Branch strategy

Work continues on the existing `dev/project-scaffold` branch because `dev/parth` did not exist. Creating another development branch would add no value and would violate the goal of keeping the repository branch model small.

Current intended flow:

```text
dev/project-scaffold -> main
```

No PR is required for every small development commit; the branch exists to accumulate coherent work before main is updated.

## 2. Why the repository stays Python-first

The research core is Python because the project needs fast iteration on feature extraction, embeddings, classical ML baselines, evaluation, and security experiments.

Current libraries:

- **Pydantic**: typed validation/serialization for snapshots, deltas, risk assessments, and runtime results. It is used instead of raw dictionaries/dataclasses at the trust boundary because malformed security data should fail clearly.
- **scikit-learn** *(optional `ml` extra)*: planned for transparent pairwise baselines and classical models. It is easier to inspect and reproduce than introducing a deep-learning training stack immediately.
- **sentence-transformers** *(optional `ml` extra)*: planned for field-level semantic distances and pairwise embeddings. It is not a hard dependency so the core detector can run without downloading a model.
- **FastAPI + Uvicorn** *(optional `api` extra)*: reserved for a later local/service API. They are optional because the detector itself should not depend on a web server.
- **pytest**: unit/integration tests.
- **Ruff**: fast linting with little configuration overhead.

We are intentionally **not** using LangChain/LlamaIndex as core infrastructure. DriftGuard is a security control for MCP definitions, so its core should stay protocol-focused and framework-independent.

## 3. Structural decision

The original research functions remain in small top-level modules because they are already cohesive:

```text
src/driftguard/
├── models.py          # domain models
├── canonicalize.py    # deterministic snapshot + hash
├── diff.py            # pairwise structural/lexical deltas
├── baselines.py       # reproducible baseline detector
├── runtime/           # trust, policy, orchestration
└── adapters/          # external MCP payload conversion
```

This avoids a premature rewrite into many tiny packages while still separating product/runtime concerns from research code.

## 4. Main runtime call flow

The intended call path is:

```text
MCP tools/list
  -> adapters.mcp.extract_tools(payload)
  -> DriftGuardService.observe_tool(...)
      -> make_snapshot(...)
      -> SnapshotStore.get_trusted(...)
      -> build_delta(...)
      -> detector(delta)              # defaults to rule_baseline
      -> DefaultPolicy.decide(...)
  -> ObservationResult
```

### What the major functions do

- `extract_tools(payload)`: called by an MCP-facing interceptor/host integration. It extracts tool dictionaries from a direct `tools/list` result or JSON-RPC response.
- `make_snapshot(...)`: called by `DriftGuardService.observe_tool`. It canonicalizes the tool definition, computes its stable hash, and wraps it in `ToolSnapshot`.
- `build_delta(old, new)`: called by `DriftGuardService.observe_tool` once a trusted baseline exists. It creates structural signals and a lexical change ratio between versions.
- `rule_baseline(delta)`: the default detector injected into `DriftGuardService`. It produces a `RiskAssessment`; later ML detectors can use the same callable interface.
- `DefaultPolicy.decide(assessment)`: called after detection. It maps C0-C3 into operational actions. Policy is separate from classification so an organization can change enforcement without retraining a model.
- `DriftGuardService.approve(snapshot)`: called only after explicit review/consent. It promotes that observed snapshot to the trusted comparison baseline.

## 5. Storage decision

`SnapshotStore` is a Python `Protocol`, not a database-specific base class. This keeps the runtime independent of SQLite/Postgres/Redis while still defining exactly what storage must provide.

`InMemorySnapshotStore` is used now for tests and demos. It is not intended to be the production audit store.

Likely next durable implementation: SQLite first for local development, then Postgres for multi-user/server deployments. That decision should be made when persistence/audit requirements are implemented rather than adding database dependencies now.

## 6. Security decisions in this scaffold

- First-seen tools are **not** silently trusted. They return `require_reconsent`.
- Detector output and enforcement policy are separate layers.
- Approved snapshots are the comparison baseline; merely observing a version does not automatically approve it.
- Adapters are kept outside the detector so malformed transport data can be handled before it reaches research logic.

## 7. UI decision intentionally deferred

No React/Next.js/Tauri/Electron frontend has been committed yet. The ongoing product/UI research should decide whether the best experience is a web dashboard, local desktop shell, terminal-first client, or a hybrid.

Whichever UI is chosen should consume the runtime/API result model instead of directly calling `diff.py` or `baselines.py`.

## 8. Tests added with this structure

Runtime tests cover:

- a first observation requiring explicit approval,
- an approved snapshot becoming the trusted baseline,
- suspicious drift not being auto-approved,
- MCP JSON-RPC tool extraction.

These tests protect the trust lifecycle, not only individual helper functions.

## 9. Near-term structure additions

Next additions should be driven by actual implementation needs, roughly in this order:

1. durable snapshot/audit store,
2. MCP interceptor/host integration,
3. detector interface + feature pipeline for learned models,
4. experiment/evaluation harness and versioned datasets,
5. policy configuration and approval records,
6. API/CLI surface,
7. polished operator UI after the UX architecture is finalized.

The repository should avoid adding placeholder folders that have no executable or documented purpose.


## 10. Durable local trust and audit history

Implemented `SQLiteSnapshotStore` as the first durable store.

Why SQLite first:

- it is included in Python, so no new runtime dependency is required,
- it survives process restarts, unlike `InMemorySnapshotStore`,
- it is easy to inspect during a college demonstration,
- it provides a migration path to Postgres later without changing `DriftGuardService`.

The database keeps two concepts separate:

- **observations**: append-only tool snapshots used for version history and later experiments,
- **trusted snapshots**: the currently approved baseline for each server/tool pair.

The runtime still depends only on the `SnapshotStore` protocol. SQLite is therefore an implementation choice, not a dependency baked into the detector.

## 11. First real MCP enforcement boundary

Implemented `adapters.mcp.intercept_tools_list(...)`.

Updated call flow:

```text
MCP server tools/list response
  -> intercept_tools_list(...)
      -> extract_tools(...)
      -> DriftGuardService.observe_tool(...) for every tool
      -> policy decision
      -> safe tools are forwarded
      -> re-consent/quarantine tools are withheld
  -> filtered tools/list response reaches the host/LLM
```

Important behavior:

- a first-seen tool is withheld until explicitly approved,
- an unchanged approved tool is forwarded,
- a suspicious changed tool is withheld again,
- the original JSON-RPC envelope is preserved.

This gives DriftGuard an executable security-control point rather than only producing an offline risk score.

## 12. Research direction opened by this batch

Durable version history plus an enforcement boundary now makes the next research additions practical:

1. cumulative drift / drift-budget experiments over observation history,
2. trust decay and temporal reputation,
3. approval/audit records with reviewer identity and reason,
4. semantic embedding detector plugged into the existing detector callable,
5. benchmark/evaluation harness comparing hash, structural, lexical, semantic, and hybrid models,
6. real transport proxy/host integration around this interception function.

No frontend framework has been added yet; the interception result and durable history should become the stable backend contract that the later operator UI consumes.


## 13. Cumulative drift budget

Implemented `runtime.temporal.DriftBudget` as the first research-specific temporal defense.

### Threat being tested

A server can avoid one obvious malicious update by making many small changes and asking the user to approve each one. If each new version becomes the trusted baseline, a purely pairwise detector can lose sight of how far the tool has moved over time.

### Current mechanism

For the most recent configurable window of observed versions:

1. compare each consecutive version,
2. run the same injected detector on each transition,
3. accumulate the transition risk scores,
4. expose the individual steps plus the cumulative score as `DriftBudgetEvidence`,
5. require re-consent when the cumulative budget is exceeded even if the current pair is only C0/C1.

Default research parameters are currently a 5-transition window and a budget of 100. These are deliberately configurable and should later be learned/tuned on the benchmark dataset instead of being presented as universal values.

### Why approval does not reset the budget

The purpose is to detect low-and-slow drift across individually accepted updates. Approving version N changes the direct comparison baseline, but it does not erase observation history. This lets the project experimentally compare:

- pairwise-only detection,
- trusted-baseline detection,
- rolling cumulative drift,
- future trust-decay/reputation variants.

The temporal evidence is also designed for the future UI: it can drive a version timeline and a visible drift-budget meter.


## 14. Reproducible benchmark and evaluation harness

Implemented `driftguard.evaluation`, `data/synthetic_v0.jsonl`, and
`experiments/evaluate_rule_baseline.py`.

The first benchmark is intentionally small and synthetic. Its purpose is to establish the
research contract before collecting a larger dataset:

- every sample stores the old tool, new tool, semantic label, and attack/change family,
- labels are independent of the current detector,
- predictions are retained in the report so individual failures are inspectable,
- reports include accuracy, per-class precision/recall/F1, macro F1, and a confusion matrix.

The metric implementation uses only the Python standard library plus existing Pydantic
models. scikit-learn remains optional because basic evaluation should run in the minimal
installation.

Run:

```bash
python experiments/evaluate_rule_baseline.py
```

A low score is not treated as a repository failure. The current rule detector is a
baseline. Its mistakes identify exactly which cases should be improved by the next
semantic embedding, hybrid, temporal, and uncertainty-aware detectors.

Future dataset versions should add provenance, multiple annotators, paraphrase variants,
unseen attack-family splits, and benign real-world MCP schema evolution.


## 15. Explainable scoring and counterfactual evidence

The rule baseline now emits typed `RiskContribution` objects in addition to human-readable
reasons. Each contribution contains a signal name, the points added to the score, and the
specific evidence that caused it.

Examples include:

- sensitive terms added,
- required parameters added,
- imperative/instruction terms,
- external URLs,
- cross-tool references,
- lexical change.

`greedy_counterfactual(...)` then asks a narrow, inspectable question: which largest
rule contributions would need to disappear for the score to cross the next safer rule
boundary?

This is deliberately described as a **rule-baseline explanation**, not causal proof.
Future learned detectors will need model-appropriate explainers. The stable runtime
`ObservationResult` now exposes the counterfactual so the eventual UI can show both
"why this was blocked" and "what evidence drove the decision."

C1-to-C0 is not claimed from score reduction because C0 requires canonical equivalence,
not merely a score below a threshold.
