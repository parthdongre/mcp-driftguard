# Tamper-evident review audit

DriftGuard's approval/rejection history is now hash-chained per `(server_id, tool_name)`.

Each `ReviewEvent` stores:

- snapshot SHA-256,
- reviewer and decision,
- optional human reason,
- review timestamp,
- `previous_event_hash`,
- `event_hash`.

The event hash is calculated from a deterministic JSON representation of the entire event except `event_hash` itself. The previous event's hash is included in that payload, so changing, deleting, reordering, or rewriting a sealed review event breaks verification of the chain from that point onward.

This is intentionally a tamper-**evident** design, not a claim that local SQLite storage is tamper-proof. An attacker with full control of the database and application secrets could rewrite an entire unsigned chain. The next hardening step for production-grade deployments would be an external trust anchor such as signed checkpoints, hardware-backed signing, or periodic publication of the chain head to an independent system.

## Verification

Use:

```python
from driftguard.runtime import verify_review_chain

report = verify_review_chain(store.reviews("server", "tool"))
```

The optional HTTP control plane exposes the same verification at:

```text
GET /v1/servers/{server_id}/tools/{tool_name}/reviews/integrity
```

The report includes whether the chain is valid, the number of events, the current chain-head hash, and the first invalid event index when verification fails.

## Research relevance

This separates two properties that should be evaluated independently:

1. **detection integrity** — whether DriftGuard classifies semantic/tool drift correctly;
2. **governance integrity** — whether the record of who approved or rejected a version can be altered without detection.

That distinction is useful for an MCP security paper because a strong detector is insufficient if later review history can be silently rewritten.
