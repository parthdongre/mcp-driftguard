# MCP DriftGuard engineering map

This is the compact overview of the repository: architecture, major function calls, library choices, research features, and what should be built next.

## Branch strategy

Use the existing development path only:

```text
dev/project-scaffold -> main
```

Do not create extra branches unless isolation is actually required.

## Why Python

The research core stays Python because the project needs fast iteration on security features, embeddings, classical ML, evaluation, local middleware, and experiments.

Key libraries:

- **Pydantic** — typed security/domain models and validation.
- **scikit-learn** (`ml` extra) — interpretable learned baselines.
- **sentence-transformers** (`semantic` extra) — optional embedding backend.
- **FastAPI + Uvicorn** (`api` extra) — optional control plane for CLI/UI clients.
- **SQLite / sqlite3** — durable local snapshots, trust state, and audit history without a new DB dependency.
- **pytest + Ruff** — verification and linting.

LangChain/LlamaIndex are intentionally not core dependencies; DriftGuard should stay MCP- and host-neutral.

## Main architecture

```text
MCP tools/list
   -> adapters.mcp.intercept_tools_list
       -> extract tools
       -> analyze cross-tool graph
       -> DriftGuardService.observe_tool
           -> canonicalize.make_snapshot
           -> SnapshotStore.put_observed / get_trusted
           -> diff.build_delta
           -> detector(delta)
           -> DriftBudget.evaluate(history)
           -> policy decision
           -> optional explanation
       -> safe tools forwarded
       -> re-consent/quarantine tools withheld
```

Research internals are separated from HTTP/UI/host integration.

## Important functions

- `make_snapshot(...)` — canonical tool identity + SHA-256.
- `build_delta(old, new)` — structural and lexical pairwise evidence.
- `pair_features(delta)` — stable numeric contract for learned models.
- `semantic_pair_features(...)` — provider-neutral field-level semantic distances.
- `rule_baseline(delta)` — transparent hand-written baseline.
- `PairwiseLogisticDetector` — learned structural/lexical baseline.
- `HybridSemanticLogisticDetector` — structural + semantic learned baseline.
- `DriftBudget.evaluate(...)` — cumulative low-and-slow drift.
- `analyze_tool_graph(...)` — complete discovery-surface influence graph.
- `diff_tool_graph(old, new)` — topology drift.
- `graph_rule_baseline(...)` — transparent topology-risk baseline.
- `DefaultPolicy.decide(...)` — maps detection into enforcement.
- `DriftGuardService.approve(...)` / `reject(...)` — auditable trust decisions.
- `verify_review_chain(...)` — verifies review-log integrity.

## Trust and persistence

`SnapshotStore` is a protocol with in-memory and SQLite implementations.

The system separates:

1. observed tool versions,
2. currently trusted baseline,
3. human approval/rejection history.

First-seen tools are never silently trusted. Rejection never replaces the trusted baseline.

## Detector progression

The current research ladder is:

1. hash-only change detection,
2. rule baseline,
3. learned structural/lexical pair classifier,
4. semantic distances,
5. hybrid structural + semantic classifier,
6. temporal drift budget,
7. graph/topology drift,
8. deeper pair/Siamese models only if a larger dataset justifies them.

All models should be evaluated through reproducible benchmark contracts rather than qualitative demos.

## Uncertainty and explainability

Learned detectors expose confidence and can abstain on low-confidence or low-margin predictions. Abstention keeps the C0-C3 prediction for research metrics but policy escalates the operational action to re-consent.

The rule baseline also emits named risk contributions and a bounded counterfactual explanation. This is an explanation of the rule system, not a causal security proof.

## Temporal drift

`DriftBudget` detects a "boiling frog" attack where many accepted small changes accumulate into material semantic drift. Approval changes the direct comparison baseline but does not erase history.

This enables experiments comparing pairwise-only, trusted-baseline, and rolling temporal detection.

## Cross-tool graph research

The graph layer records tool-to-tool references, imperative redirects, sensitive-looking targets, unresolved references, cycles, and topology changes.

The version-aware delta additionally exposes new imperative edges and new sensitive-target edges.

`data/graph_synthetic_v0.jsonl` is the first labeled graph-evolution benchmark. `graph_rule_baseline(...)` is evaluated separately and remains **evidence-only** for enforcement until the graph corpus is large enough to estimate false positives reliably.

Run:

```bash
python experiments/evaluate_graph_baseline.py
```

The report includes accuracy, precision, recall, F1, TP/FP/TN/FN, and every prediction.

## Pairwise benchmark discipline

`data/synthetic_v0.jsonl` contains labeled old/new tool pairs. Metrics include accuracy, per-class precision/recall/F1, macro-F1, confusion matrix, and per-sample predictions.

Labels describe intended security semantics and are not changed to make a detector score better. Learned experiments use leave-one-out evaluation on the prototype corpus rather than reporting training accuracy.

Publication claims require a much larger dataset with provenance, independent annotation, paraphrase/adversarial variants, real benign MCP evolution, held-out attack families, and multi-tool cases.

## Review audit integrity

Approval/rejection records contain the exact snapshot hash, reviewer, decision, optional reason, and timestamp.

Review events are now hash-chained per `(server_id, tool_name)` using `previous_event_hash` + `event_hash`. Editing, deleting, inserting, or reordering a sealed event breaks verification from that point.

This is **tamper-evident**, not tamper-proof. A privileged attacker who can rewrite the entire unsigned database can rebuild the chain. Production hardening should anchor/sign chain heads externally.

## API control plane

The optional FastAPI backend is the stable boundary for future CLI/UI clients.

Important operations:

```text
POST /v1/servers/{server}/tools/intercept
POST /v1/servers/{server}/tools/{tool}/approve
POST /v1/servers/{server}/tools/{tool}/reject
GET  /v1/servers/{server}/tools/{tool}/reviews
GET  /v1/servers/{server}/tools/{tool}/reviews/integrity
```

Review operations are hash-addressed: the caller must identify the exact observed snapshot SHA-256.

## UI contract

The eventual Codex/Claude-Code-quality interface should consume runtime/API objects rather than import detector internals directly.

Backend evidence already supports:

- tool/version timeline,
- before/after schema diff,
- risk-contribution explanation,
- confidence/abstention display,
- temporal drift-budget meter,
- cross-tool influence graph,
- review history,
- audit-integrity indicator.

## Next priorities

1. experiment combining pairwise + temporal + graph signals,
2. externally anchored or signed audit checkpoints,
3. configurable organization policy/thresholds,
4. real MCP transport proxy/host integration,
5. CLI for local inspection/review,
6. polished operator UI over the API contract,
7. substantially expand both pairwise and graph datasets before making accuracy claims.

Avoid placeholder modules and dependencies that do not yet serve an executable or experimental purpose.
