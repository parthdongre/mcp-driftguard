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
