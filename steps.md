# MCP DriftGuard engineering map

This file is the compact technical overview of the repository: what the major layers do, why the main libraries were chosen, where important functions are called, and what research questions the current implementation supports.

## 1. Branch strategy

Development remains on the existing `dev/project-scaffold` branch to keep the repository branch model small.

```text
dev/project-scaffold -> main
```

Do not create extra development branches unless isolation is genuinely required.

## 2. Why the project is Python-first

The research core is Python because DriftGuard needs fast iteration on feature extraction, embeddings, classical ML, evaluation, security experiments, and local middleware.

Main dependencies:

- **Pydantic** — typed models and validation across trust boundaries.
- **scikit-learn** (`ml` extra) — interpretable/reproducible classical learned baselines.
- **sentence-transformers** (`semantic` extra) — optional semantic embeddings without forcing model downloads into the minimal install.
- **FastAPI + Uvicorn** (`api` extra) — optional local/service control plane for CLI/UI clients.
- **pytest** — tests.
- **Ruff** — linting.
- **SQLite / sqlite3** — durable local audit/history storage without adding a database dependency.

The core intentionally does **not** depend on LangChain or LlamaIndex. DriftGuard is an MCP security layer and should remain host/framework neutral.

## 3. Repository architecture

```text
src/driftguard/
├── models.py          # domain objects and risk assessments
├── canonicalize.py    # deterministic tool snapshots + hashes
├── diff.py            # structural / lexical pairwise deltas
├── features.py        # stable numeric pairwise features
├── semantic.py        # provider-neutral semantic features / embedders
├── ml.py              # learned pairwise + hybrid detectors
├── graph.py           # cross-tool influence graph + topology drift
├── baselines.py       # hash/rule baselines
├── explain.py         # explainable risk contributions / counterfactuals
├── evaluation.py      # benchmark metrics and reports
├── api.py             # optional HTTP control plane
├── runtime/           # trust, policy, persistence, audit, temporal logic
└── adapters/          # MCP payload/interception boundary
```

Research code stays separated from HTTP, UI, and host-specific integration.

## 4. Main MCP enforcement flow

```text
MCP server tools/list
        |
        v
adapters.mcp.intercept_tools_list
        |
        +--> extract_tools
        +--> graph analysis
        |
        v
DriftGuardService.observe_tool
        |
        +--> make_snapshot
        +--> SnapshotStore.put_observed
        +--> SnapshotStore.get_trusted
        +--> build_delta
        +--> detector(delta)
        +--> DriftBudget.evaluate(history)
        +--> policy decision
        +--> optional explanation
        |
        v
ObservationResult
        |
        +--> allow / allow+log -> forwarded
        +--> re-consent / quarantine -> withheld
```

A first-seen tool is withheld until reviewed. Merely observing a tool never promotes it to the trusted baseline.

## 5. Important function boundaries

- `make_snapshot(...)` — canonicalizes one tool definition and computes the stable SHA-256 identity.
- `build_delta(old, new)` — creates structural and lexical pairwise evidence.
- `pair_features(delta)` — converts pairwise evidence into the stable numeric feature contract used by learned models.
- `semantic_pair_features(...)` — measures field-level semantic distances through an injected embedder.
- `rule_baseline(delta)` — transparent non-ML baseline.
- `PairwiseLogisticDetector` — learned structural/lexical baseline.
- `HybridSemanticLogisticDetector` — structural + semantic learned baseline.
- `DriftBudget.evaluate(...)` — detects cumulative low-and-slow drift across multiple versions.
- `build_tool_graph(...)` — constructs cross-tool influence evidence from a complete tool surface.
- `diff_tool_graph(old, new)` — measures topology drift between discovery surfaces.
- `DefaultPolicy.decide(...)` — maps semantic risk to operational action.
- `intercept_tools_list(...)` — executable security gate before tool definitions reach the host/LLM.
- `DriftGuardService.approve(...)` / `reject(...)` — auditable trust decisions.
- `verify_review_chain(...)` — independently verifies the tamper-evident review chain.

## 6. Persistence and trust

`SnapshotStore` is a protocol, not a database-specific base class.

Implementations:

- `InMemorySnapshotStore` — deterministic tests/demos.
- `SQLiteSnapshotStore` — durable local history, trusted snapshots, and review events.

The store separates:

- observed tool versions,
- currently trusted baseline,
- append-only human review events.

This keeps observation, trust, and governance as different concepts.

## 7. Detection progression

The project deliberately supports progressively stronger comparisons:

1. hash-only change detection,
2. hand-written rule baseline,
3. learned structural/lexical pair classifier,
4. semantic distances,
5. hybrid structural + semantic classifier,
6. temporal drift budget,
7. cross-tool topology drift,
8. future deeper pair encoder / Siamese model only if the dataset justifies it.

The same benchmark/evaluation boundary should be used for all models so improvements are measurable rather than qualitative.

## 8. Uncertainty-aware abstention

Learned detectors expose confidence and can abstain when:

- maximum class probability is too low, or
- the margin between the top two classes is too small.

Abstention does not create a fifth semantic class. The predicted C0-C3 class remains available for evaluation, while operational policy escalates uncertain results to re-consent.

This allows classification quality and safety-under-uncertainty to be measured separately.

## 9. Explainability

The rule baseline emits named `RiskContribution` objects such as:

- sensitive terms,
- required parameters,
- imperative language,
- external URLs,
- cross-tool references,
- lexical drift.

`greedy_counterfactual(...)` explains which large rule contributions would need to disappear to cross the next safer rule threshold.

This is explicitly an explanation of the rule baseline, not a causal security proof.

## 10. Temporal drift budget

Pairwise review alone can miss a "boiling frog" attack where each accepted update is individually small.

`DriftBudget` therefore evaluates consecutive observations over a rolling window and accumulates risk. Approval changes the trusted direct-comparison baseline but does **not** erase observation history.

Research comparisons can therefore test:

- pairwise-only,
- trusted-baseline,
- cumulative temporal drift,
- future trust-decay/reputation variants.

## 11. Cross-tool graph research

Tool definitions are also analyzed as a system.

Graph evidence includes:

- explicit tool-to-tool references,
- imperative redirects,
- references toward sensitive-looking tools,
- unresolved references,
- cycles.

`diff_tool_graph(...)` additionally measures:

- edges added/removed,
- tools added/removed,
- cycles introduced/resolved,
- changes in graph-level suspicion.

Graph evidence remains separate from default blocking until labeled graph-evolution benchmark coverage is large enough to estimate false positives.

## 12. Benchmark and experimental discipline

`data/synthetic_v0.jsonl` is the initial labeled old/new tool-pair corpus.

`evaluation.py` reports:

- accuracy,
- per-class precision/recall/F1,
- macro-F1,
- confusion matrix,
- individual predictions.

Labels represent intended security semantics and are not changed to make the current baseline score better.

Learned experiments use leave-one-out evaluation on the tiny prototype dataset rather than reporting training accuracy. Publication claims require a much larger corpus with provenance, independent annotation, paraphrase/adversarial variants, unseen-family splits, and real benign MCP evolution.

## 13. Review and approval audit

Every approval/rejection records:

- server/tool identity,
- exact observed snapshot hash,
- decision,
- reviewer identifier,
- optional reason,
- timestamp.

Rejection never replaces the trusted baseline.

The reviewer string is still application-supplied; real authentication/identity integration belongs at the control-plane boundary.

## 14. Tamper-evident review chain

Review events are now hash-chained per `(server_id, tool_name)`.

Each event stores `previous_event_hash` and `event_hash`. The digest covers the complete deterministic event payload including the previous digest. Editing, reordering, inserting, or deleting a sealed event therefore breaks verification from the affected position.

`verify_review_chain(...)` returns:

- whether the chain is valid,
- event count,
- chain-head hash,
- first invalid index and reason when verification fails.

Important limitation: this is **tamper-evident**, not tamper-proof. An attacker controlling the whole local database could rewrite an entire unsigned chain. Production hardening should anchor chain heads externally or sign checkpoints with a protected key/HSM.

## 15. HTTP control plane

The optional FastAPI surface provides a stable backend contract for a future CLI/desktop/web UI.

Current high-value operations include:

```text
POST /v1/servers/{server}/tools/intercept
POST /v1/servers/{server}/tools/{tool}/approve
POST /v1/servers/{server}/tools/{tool}/reject
GET  /v1/servers/{server}/tools/{tool}/reviews
GET  /v1/servers/{server}/tools/{tool}/reviews/integrity
```

Approvals/rejections are hash-addressed: the caller must name the exact observed snapshot SHA-256 being reviewed.

## 16. UI contract

The UI should consume stable runtime/API objects rather than import `diff.py`, `ml.py`, or other research internals directly.

Useful operator views are now naturally supported by backend evidence:

- tool/version timeline,
- before/after schema diff,
- risk contributions,
- confidence/abstention state,
- temporal drift-budget meter,
- cross-tool influence graph,
- approval/rejection history,
- audit-chain integrity indicator.

A polished UI should prioritize these operator workflows over generic dashboard decoration.

## 17. Current next priorities

Highest-value next work:

1. labeled graph/topology-evolution benchmark cases,
2. experiment comparing pairwise vs temporal vs graph-aware decisions,
3. externally anchored/signed audit checkpoints,
4. configurable organization policy and thresholds,
5. actual MCP transport proxy/host integration around the interceptor,
6. CLI for local operation/debugging,
7. Codex/Claude-Code-quality operator UI over the existing API contract,
8. expand the dataset before making accuracy claims.

The repository should keep avoiding placeholder folders and dependencies that do not yet serve an executable or experimental purpose.
