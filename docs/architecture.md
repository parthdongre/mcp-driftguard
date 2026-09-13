# Architecture

MCP DriftGuard is split into a small set of layers so the detector can evolve without coupling research code to a particular MCP client, database, or UI.

```text
MCP tools/list payload
        |
        v
adapters.mcp.extract_tools
        |
        v
runtime.DriftGuardService.observe_tool
        |
        +--> canonicalize.make_snapshot
        |
        +--> SnapshotStore.get_trusted
        |
        +--> diff.build_delta
        |
        +--> detector(delta)
        |      default: baselines.rule_baseline
        |
        +--> DefaultPolicy.decide
        |
        v
ObservationResult
  snapshot + delta + assessment + enforcement decision
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

- `store.py` defines the snapshot-storage contract and an in-memory implementation.
- `policy.py` converts model classes into enforcement actions.
- `service.py` orchestrates snapshot creation, trusted-baseline lookup, delta construction, detection, and policy.

Keeping policy separate from the detector is important: a classifier estimates risk, while policy decides what the product is allowed to do with that estimate.

### Adapters

`adapters/` converts external formats into DriftGuard inputs. The first adapter extracts tools from MCP `tools/list` / JSON-RPC responses. Future adapters can support host-specific transports without changing the detector.

### UI/API boundary

A UI and API are intentionally not chosen yet. They should consume `ObservationResult` rather than importing low-level detection functions directly. This keeps the future dashboard replaceable and makes CLI, desktop, and web clients possible over the same runtime.

## Trust workflow

A first-seen tool is never silently trusted by the runtime. It returns `require_reconsent`. A caller must explicitly approve the reviewed snapshot with `DriftGuardService.approve(...)`. Later observations are compared to that approved baseline.

Durable persistence, signed approvals, organization policy, and audit events are future storage/policy implementations behind the same interfaces.
