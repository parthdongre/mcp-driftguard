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

## Product mental model

DriftGuard should behave like **GitHub/version control for MCP discovery surfaces**.

Every `tools/list` observation is a revision with:

- a unique revision ID,
- a complete surface/tree hash,
- a parent revision,
- exact tool hashes,
- previous-vs-current diff,
- current-vs-trusted status.

The system should always be able to answer: what changed, when did it change, what is new/removed/modified, and how far is current state from approved state.

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
- `make_discovery_revision(...)` — creates a commit-like complete MCP surface revision.
- `diff_revisions(old, new)` — Git-style added/removed/modified/unchanged tool diff.
- `compare_to_trusted(...)` — current surface vs approved per-tool baselines.

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

## Revision/change ledger

The repository now keeps complete discovery revisions in addition to individual tool snapshots.

This enables Git-like operations:

```text
driftguard status
driftguard log
driftguard diff --from <revision> --to <revision>
```

The API similarly exposes server status, revision history, individual revisions, and arbitrary revision comparison.

A revision is an observation/commit; its `tree_hash` represents the complete tool surface. Repeated identical surfaces may therefore have different revision IDs but the same tree hash, preserving both content identity and observation history.

A cursor-based change feed now derives compact events from the immutable revision chain. This supports both polling APIs and a CLI watch mode without changing the revision model.

Useful local commands:

```text
driftguard status --db driftguard.db --server demo
driftguard freshness --db driftguard.db --server demo
driftguard log --db driftguard.db --server demo
driftguard diff --db driftguard.db --server demo --from <rev> --to <rev>
driftguard changes --db driftguard.db --server demo --after <rev>
driftguard watch --db driftguard.db --server demo
driftguard blame --db driftguard.db --server demo --tool search
driftguard check --db driftguard.db --server demo
driftguard show --db driftguard.db --server demo [<revision>]
driftguard timeline --db driftguard.db --server demo
```

The default CLI output is intentionally Git-like and human-readable. Modified tools also expose exact JSON-pointer paths (for example `/description` or `/inputSchema/properties/api_token`) so operators can review precise field-level changes. Arrays are intentionally treated atomically to avoid unstable index-level diffs. Add `--json` where supported for automation/UI plumbing.

### Field provenance / blame

`blame_tool(...)` walks the immutable revision history and records the revision that most recently introduced or changed every current leaf field. This allows questions such as "when did the API-token capability appear?" without manually comparing every version.

`driftguard blame` supports an optional historical revision and a JSON-pointer prefix. For example, `--path /inputSchema/properties/api_token` returns provenance for that capability subtree. If a target revision contains duplicate definitions with the same tool name, blame is explicitly marked ambiguous rather than guessing.

## Unified activity timeline

`build_server_timeline(...)` merges four durable event streams into one newest-first feed:

1. server `tools/list_changed` notifications,
2. discovery revisions and their provenance/change summaries,
3. immutable security checks,
4. human approval/rejection events.

The CLI and API expose the same read model:

```text
driftguard timeline --db driftguard.db --server demo
GET /v1/servers/{server}/timeline
```

This is the intended backend contract for a GitHub-style repository activity page and makes
incident reconstruction much easier: an operator can see the server announcement, the
resulting refresh revision, its security verdict, and any subsequent human decision in one
chronological stream.

## Revision provenance

Each discovery revision now records two provenance dimensions:

- **channel** — direct adapter, HTTP API, or transparent stdio proxy,
- **trigger** — initial discovery, ordinary discovery/poll, or refresh after a server
  `notifications/tools/list_changed` signal.

A refresh revision also records how many pending server change signals it acknowledged.
This makes the history explain *why* a revision exists instead of only storing its content.

The provenance is included in `driftguard log` and `driftguard show`, and is part of the
immutable revision ID payload.

## Git-show-style revision view

`RevisionView` is the primary read model for an operator opening a revision. It combines:

- immutable revision metadata,
- exact parent-to-revision diff,
- the persisted security check from observation time,
- current catalog freshness only when viewing the latest revision.

This deliberately separates historical facts from current state. A historical revision never
inherits today's freshness signal, while its original security verdict remains preserved.

Use:

```text
driftguard show --db driftguard.db --server demo [<revision>]
```

The API equivalent is:

```text
GET /v1/servers/{server}/revisions/{revision}/view
```

This object is intended to back the eventual GitHub-like revision page in the UI.

## Immutable revision security checks

Every intercepted discovery revision receives a persisted security check, similar to a
GitHub commit check. The check records the exact detector and policy names plus the
per-tool action, risk score, C0-C3 class, confidence/abstention state, and temporal
evidence that existed **when the revision was observed**.

This matters because future detector or policy changes must not silently rewrite historical
decisions. An operator can inspect the original verdict with:

```text
driftguard check --db driftguard.db --server demo [--revision <rev>]
```

The API exposes both per-revision checks and the full check history.

## Catalog freshness / server change signals

MCP servers can announce catalog changes with `notifications/tools/list_changed`.
DriftGuard persists each observed signal immediately and marks the known tool catalog
**dirty** until a subsequent `tools/list` response is intercepted and committed as a new
revision.

This distinguishes two states that normal snapshot scanners often collapse:

```text
clean: latest observed revision is current as far as DriftGuard knows
dirty: server announced a change, refreshed catalog has not been observed yet
```

One refreshed discovery revision acknowledges all pending change signals. The signal
history remains durable in SQLite, so an operator can tell that a refresh happened in
response to one or more server announcements.

## Transparent stdio MCP proxy

`driftguard proxy` now provides the first real transport integration.

It launches a local MCP server as a child process, transparently forwards JSON-RPC traffic,
tracks client request IDs, and intercepts only responses corresponding to `tools/list`.
Those discovery responses pass through the same version ledger, risk detection, policy, and
tool filtering as the direct adapter/API path.

Example:

```bash
driftguard proxy --db driftguard.db --server filesystem -- python my_mcp_server.py
```

All proxy diagnostics go to stderr so stdout remains a clean MCP protocol channel. Invalid
or unrelated output is passed through unchanged. If DriftGuard itself fails while inspecting
a `tools/list` response, the proxy fails closed by returning an empty tool list and writing
the error to stderr.

This raw JSON-RPC proxy is intentionally SDK-neutral and supports the stdio deployment model
without making the research core depend on a particular MCP SDK.

## Fusion / ablation experiment

`fusion.py` and `fusion_evaluation.py` provide a common binary "intervention required"
experiment across multi-revision scenarios.

The same scenario is evaluated under six configurations:

1. pairwise only,
2. temporal only,
3. graph only,
4. pairwise + temporal,
5. pairwise + graph,
6. full pairwise + temporal + graph fusion.

`data/fusion_synthetic_v0.jsonl` currently includes direct escalation, gradual low-and-slow
drift, sensitive cross-tool routes, cycles, and benign controls. The report gives
TP/FP/TN/FN, accuracy, precision, recall, and F1 for every ablation.

Run:

```bash
driftguard benchmark fusion
```

The prototype temporal budget is an experimental parameter, not a production threshold.
The purpose of this harness is to make component contribution measurable and eventually
produce a defensible paper ablation table on a much larger corpus.

## Next priorities

1. expand the unified multi-revision benchmark and run held-out-family ablations,
2. Streamable HTTP gateway/interceptor for remote MCP servers,
3. automatically establish the MCP tools-list-change subscription where supported,
4. server-push subscription (SSE/WebSocket) over the DriftGuard change feed,
5. externally anchored or signed audit checkpoints,
6. configurable organization policy/thresholds,
7. polished GitHub/Codex-like operator UI over revision history and diffs,
8. substantially expand both pairwise and graph datasets before making accuracy claims.

Avoid placeholder modules and dependencies that do not yet serve an executable or experimental purpose.
