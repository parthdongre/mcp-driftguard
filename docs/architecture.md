# Architecture

MCP DriftGuard is split into a small set of layers so the detector can evolve without coupling research code to a particular MCP client, database, or UI.

```text
MCP tools/list payload
        |
        v
adapters.mcp.intercept_tools_list
        |
        +--> adapters.mcp.extract_tools
        |
        v
runtime.DriftGuardService.observe_tool
        |
        +--> canonicalize.make_snapshot
        |
        +--> SnapshotStore.get_trusted
        +--> SnapshotStore.put_observed
        +--> SnapshotStore.history
        |
        +--> diff.build_delta
        |
        +--> detector(delta)
        |      default: baselines.rule_baseline
        |
        +--> DriftBudget.evaluate(history, detector)
        |
        +--> DefaultPolicy.decide
        +--> DefaultPolicy.apply_temporal
        |
        v
ObservationResult
  snapshot + delta + assessment + temporal evidence + enforcement decision
        |
        v
safe tools forwarded; re-consent/quarantine tools withheld
```

## Layer responsibilities

### Core detection

The existing flat modules remain intentionally small:

- `models.py` owns typed domain objects.
- `canonicalize.py` converts an MCP tool definition into a deterministic snapshot and hash.
- `diff.py` computes pairwise structural/lexical change features.
- `baselines.py` provides reproducible non-ML baselines for experiments and demos.

These modules should not know about HTTP, databases, UI state, or a specific MCP host.

### Runtime

`runtime/` is the application layer.

- `store.py` defines the snapshot-storage contract plus in-memory and SQLite implementations.
- `temporal.py` computes a rolling cumulative drift budget over consecutive versions.
- `policy.py` converts model classes and temporal evidence into enforcement actions.
- `service.py` orchestrates snapshot creation, trusted-baseline lookup, version history, detection,
  temporal analysis, and policy.

Keeping policy separate from the detector is important: a classifier estimates risk, while policy decides what the product is allowed to do with that estimate.

### Adapters

`adapters/` converts external formats into DriftGuard inputs. The MCP adapter now extracts and intercepts `tools/list` / JSON-RPC responses. Tools that require re-consent or quarantine are withheld before the filtered payload is returned to the host.

### UI/API boundary

A UI and API are intentionally not chosen yet. They should consume `ObservationResult` rather than importing low-level detection functions directly. The result now contains temporal evidence suitable for a risk timeline, drift-budget meter, and version-by-version explanation.

## Trust workflow

A first-seen tool is never silently trusted by the runtime. It returns `require_reconsent` and is withheld by the MCP interceptor. A caller must explicitly approve the reviewed snapshot with `DriftGuardService.approve(...)`. Later observations are compared to that approved baseline.

Approval does **not** erase history. The drift budget evaluates consecutive observed versions, so a sequence of individually low-risk changes can still trigger re-consent after cumulative change exceeds the configured budget. This is intended to defend against low-and-slow or "boiling frog" tool drift.

SQLite persistence is available for local durable history. Signed approvals, organization policy, and richer audit events remain future storage/policy additions behind the same interfaces.
