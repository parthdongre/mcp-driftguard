# Opt-in gateway security model

DriftGuard is a research prototype with an explicit host integration boundary. A host or
client must use `GuardStore` and the protected transport path for the gate to apply. It
does not intercept Claude, ChatGPT, IDE extensions, other MCP clients, operating-system
traffic, or direct connections to a configured server. Running the desktop review app
alone does not route those clients through DriftGuard.

## What approval binds

An approval is a local record binding all of the following:

| Binding | Source and purpose |
| --- | --- |
| Configured `server_id` | Host-controlled identifier; names from `serverInfo` are not identities |
| Server fingerprint | Host-controlled transport/configuration identity; transport must verify it |
| `auth_context` | Opaque caller/principal context, never an OAuth token or password |
| Protocol version | Explicit version selected for that connection |
| Exact definition SHA-256 | Stable JSON with sorted object keys; all string whitespace, literal values, array ordering and extensions retained |
| Policy revision | Explicit review/enforcement configuration version |
| Current tool revision | Monotonic local observation/review/removal revision, preventing stale review actions |

The canonical semantic hash is separate. It normalizes presentation whitespace in actual
tool/schema descriptions and titles, and order of schema `required`/`enum` arrays. It
preserves data inside defaults, constants, examples, enum members and unknown extension
fields. Consent always uses the **exact** hash, so a semantically equivalent edit still
requires explicit review. This deliberately conservative initial policy avoids automatic
acceptance based on an experimental classifier.

A fingerprint is a binding supplied by a trusted host, not cryptographic remote server
attestation. A server that keeps the same identity and definition can still change its
implementation. That behavior is outside definition-drift detection.

## Catalog and review lifecycle

The host registers a server identity, retrieves the entire tool catalog, and ingests it
in one transaction. Pagination must be completed before ingestion. Duplicate names,
non-object root schemas, malformed root fields, nonfinite/non-JSON values, excess nesting
and byte/tool limits reject the catalog and invalidate invocation trust. Input/output
schemas are checked against the bundled JSON Schema 2020-12 metaschema; declared other
drafts are currently rejected. Format evaluation is disabled: this check does not run
attacker regex patterns or validate call arguments. A failed assessment also invalidates
trust. No user `$ref`, icon URL or other definition URL is fetched. A stale transport
identity cannot ingest a catalog or invalidate a newer configured binding.

The initial limits are 500 tools, 64 KiB per definition, 2 MiB per catalog and 48 nested
levels. Definitions larger than 8 KiB use exact-change manual review without lexical or
temporal scoring, bounding the cost of `SequenceMatcher` on adversarial inputs. Changed
definitions also share a 64 KiB comparison-input budget per catalog; later changes use
the same manual-review fallback when that budget is exhausted.

| State | Invocation | How it arises |
| --- | --- | --- |
| `pending` | Denied | First observation or exact definition change requiring review |
| `approved` | Eligible for current checks | Explicit review of the exact hash and current revision |
| `denied` | Denied | Explicit denial |
| `quarantined` | Denied; approval rejected | Explicit quarantine or suspicious approved-baseline/temporal evidence |
| `revoked` | Denied | Explicit revocation, removal, identity/principal/protocol change, policy change or invalidation |

Re-observing identical bytes does not clear a denial/quarantine/revocation or accumulate
repeated fictitious temporal drift. Removing a tool revokes its approval; reappearance
does not restore it. A changed quarantined definition becomes a new review object and
must independently pass the current observation and explicit review process.

Review actions require both `expected_hash` and `expected_revision`. A stale review is
rejected, including a definition that changed away and returned to the same exact bytes.
Quarantine is latched per exact hash and cannot be cleared by denial, revocation or
removal/reappearance. Quarantined definitions cannot be approved through this API. Approval of a reviewed
pending definition creates the next temporal baseline and resets accumulated evidence.

## Research evidence in the product

Changed definitions are compared to the last approved baseline for the same configured
identity and policy using the existing
`rule_baseline`, capability features and `SequentialDriftMonitor`. Temporal CUSUM state
is persisted with observations. Identical reobservations leave that state unchanged.
Denial/revocation remove invocation authority while retaining the historical baseline
for comparison; they do not erase earlier approval evidence.
These are transparent heuristic research baselines. Scores are evidence summaries, not
calibrated probabilities of compromise, proof of a tool's implementation, or publication
accuracy claims. Safety annotations are untrusted claims; keyword-based capability
inference does not establish runtime permissions.

Initial unapproved definitions have no trusted historical baseline and receive
`unreviewed` evidence. They require human review; this path does not claim initial-schema
poisoning detection. Large-definition fallback labels an edit `C2` operationally to demand
review; it does not establish that the edit is a legitimate expansion.

## Before invocation

The protected transport refreshes the complete catalog before dispatch. `authorize_call`
checks the stored identity binding, active policy, current catalog, exact approval, hash,
presence, approval state and expected revision. `dispatch` performs that check and invokes
the trusted transport callback while holding a local lock and SQLite `BEGIN IMMEDIATE`
transaction. Other cooperating store processes cannot revise local trust during the
protected dispatch. A returned `CallPermit` is descriptive evidence and is not a reusable
bearer token; dispatch must perform authorization again.

This does not eliminate the remote race between discovery and execution. MCP `tools/call`
does not carry a server-enforced expected definition hash. A malicious server can present
one definition and execute different behavior, change immediately after discovery, omit
notifications, or return malicious output. The gate makes no claim to prevent those
behaviors. Output policy, argument schema validation, authorization and execution
sandboxing require complementary transport/host/server controls.

## Persistence, audit and trust assumptions

SQLite stores exact observed definitions, approvals, revisions, state, temporal evidence
and audit metadata. Default reopening adopts the stored policy revision. An explicitly
mismatched policy cannot silently replace it; `set_policy_revision` is the explicit
invalidation operation. An already-open process with an obsolete policy fails invocation
checks. Database failures fail closed; no in-memory fallback grants approval.

The local database and host integration code are trusted. The database is not encrypted
and its audit rows are not cryptographically tamper-evident. Definitions can themselves
contain sensitive text or default values, so reviewing/exporting raw definitions requires
the same care as handling the original schema. The core call audit records tool IDs,
hashes, revisions and generic success/failure metadata, not raw tool arguments or results.
`record_event` callers must likewise provide only bounded nonsecret metadata. Transport
credentials are not an appropriate `auth_context` value.

New database files use mode `0600` and newly created state directories use `0700` on
POSIX, subject to the user's umask potentially restricting them further. Existing files
and directories retain their permissions. Database symlinks and other nonregular file
targets are rejected. Existing parent directories remain part of the trusted local
boundary; this is not protection against an attacker who can replace paths in those
directories during opening. Windows access remains governed by the user's filesystem
ACLs. HTTP credentials use endpoint-bound native OS stores or explicitly named
environment variables; they are not stored in SQLite. See the credential boundary below.

## Current MCP protocol guidance

Official sources checked on 15 October 2026:

- [2026-07-28 changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog):
  the current core is stateless; the old initialization/session architecture is not the
  design for a new 2026 transport.
- [Tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools):
  `tools/list` supports pagination; names are scoped to a server; annotations are
  untrusted; `notifications/tools/list_changed` is the exact notification method.
- [Subscriptions](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/subscriptions):
  clients explicitly request `toolsListChanged` through `subscriptions/listen`, check the
  acknowledgment and correlate stream messages using subscription metadata.
- [Caching](https://modelcontextprotocol.io/specification/2026-07-28/server/utilities/caching):
  TTL is a freshness hint rather than an immutability guarantee. Private responses must
  remain bound to the authorization context; notifications invalidate cached responses.
  Pagination provides no cross-page consistency guarantee.
- [Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http):
  HTTP adapters must implement per-message POST, required routing/version headers,
  body/header agreement, JSON/SSE responses and subscription streams. An older protocol
  adapter must be explicitly versioned and must not claim 2026 compliance.

The store is transport-independent and does not itself claim wire-protocol compliance.

## Native bridge deadline and response boundary

The native reviewer uses one 20-second deadline for queueing behind another
request, writing stdin, consuming bounded stdout/stderr and waiting for child
exit. The fixed Python module emits UTF-8 JSON bytes, independent of platform text
encoding. Strict envelope/exit checks reject malformed or success-looking output
from an unsuccessful process; the module's intentional safe error envelope on
exit 1 remains usable. Diagnostics are counted/discarded and never echoed.

Definition collection uses a separate discovery lock and a 105-second native
deadline around the collector's 90-second operation budget. It cannot hold the
review-request lock; concurrent fetches fail promptly instead of queueing. Hosted
catalog imports remain normal bounded review requests, do not launch providers,
and cannot authorize tool execution. See [hosted catalogs](HOSTED_APP_CATALOG.md).

Timeout cancellation releases the response awaits and requests direct-child
termination; it does not promise hard real-time OS termination or descendant
sandboxing. On Windows, Tokio can use internal blocking pipe workers which may
outlive cancellation when descendants retain handles. No bounded underlying-worker
lifetime or full process-tree cleanup is claimed. A review mutation may commit
before its response times out: the client must refresh, not automatically replay.

The 11 process-helper tests run with an actual installed isolated Python module.
Headless Linux validation removes only Tauri window/command wiring and verifies
all resolved dependency identities against the production lock. It does not
exercise native windows or certify the Linux GTK stack; see
[audit/DEPENDENCY_FINDINGS.md](audit/DEPENDENCY_FINDINGS.md).

## Packaged runtime and HTTP credential boundary — 17 October followup

Packaged release builds resolve one fixed engine from the installed application's
resources. They do not accept `DRIFTGUARD_PYTHON` environment overrides. Debug builds
retain the explicitly configured virtual-environment workflow. The renderer cannot
choose an executable, module, state path or command-line arguments for review IPC.
The packaged engine dispatches only the fixed bridge/gateway/credential entry points.

Harness discovery extends the fixed review bridge with `harness_scan` and
`harness_fetch`. The renderer may select an absolute project directory and a
discovered source/digest, but cannot submit a raw executable, argv, arbitrary
configuration filename or database path. The Python collector reads known Codex
and Claude configuration locations, revalidates the selection, and can launch
that configured server or the installed harness's fixed discovery command.
Selecting **Fetch definitions** authorizes startup with user permissions; this is
not sandboxing or a defense against a compromised authorized renderer. Collection
never invokes tools or starts model turns. Its `harness:` observations are
review-only and cannot authorize a live gateway identity. See
[harness connections](HARNESS_CONNECTIONS.md) for protocol, authentication and
collection limits.

The HTTP upstream validates TLS, disables redirects/ambient proxies, serializes
bounded JSON/SSE exchanges and never automatically replays failed calls.
Modern routing mirrors body metadata into required method/name/parameter headers;
invalid routing annotations withhold the affected tool. Legacy remote session
identifiers are opaque, bounded and never persisted. Modern HTTP has no such
protocol sessions; the fresh local approval nonce still separates gateway instances.

Native credential accounts bind the exact configured source identifier and HTTPS
endpoint. Store/remove actions return availability metadata only, never a stored
value. Windows uses Credential Manager; macOS uses Keychain; Linux uses Secret
Service through `secret-tool`, with no plaintext fallback. Secrets necessarily
exist in process memory while authenticating and checking output. This does not
claim memory erasure, a compromised-renderer defense, or resistance to another
process with the same local account and native-store authority. Credential unlock
may require OS interaction. No OAuth discovery/refresh implementation is claimed.

Heartbeats record process activity only and cannot create consent. Old gateway
instances cannot overwrite replacement activity. A recent local heartbeat is not
remote liveness, execution attestation or proof of systemwide interception.

The compatibility sources backport the upstream GLib mutable out-pointer fix and
replace unmaintained macro helpers. The raw dated RustSec report is retained
separately from the source-level compatibility decision; neither substitutes for
independent security review. Signing, notarization, update trust and manual native
usability/accessibility verification remain production-release requirements.
