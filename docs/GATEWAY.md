# Explicit stdio MCP protection gateway

`driftguard-gateway` is a working, opt-in, tools-only stdio mediator. It starts
one explicitly configured subprocess with a fixed argument vector, discovers its
tool catalog, and exposes definitions only after exact local approval. The desktop
review app and gateway share a SQLite state file. It does not intercept clients
that connect directly to the original server.

## Run

Install this checkout with `python -m pip install -e .`. Create a local configuration
such as the following, using your own server executable, script and directory:

```json
{
  "server_id": "my-local-server",
  "argv": ["/absolute/path/to/python", "/absolute/path/to/server.py"],
  "cwd": "/absolute/path/to/server-directory",
  "protocol_version": "2026-07-28",
  "pass_env": [],
  "timeout_seconds": 15
}
```

To connect a legacy server, explicitly choose `2025-11-25`. There is no automatic
version downgrade. HTTP URLs and shell command strings are not accepted transports.
Arguments are executed directly, with `shell=False`.

```bash
driftguard-gateway identity --config /absolute/path/to/connection.json
driftguard-gateway serve --config /absolute/path/to/connection.json --state /absolute/path/to/driftguard.sqlite3
```

Configure the MCP client to run the second command as its server, separating the
executable and arguments as required by that client's configuration format. Supply
the desktop application's default state path for `--state`; OS paths are listed
in [desktop/README.md](../desktop/README.md). The CLI review bridge can inspect an
explicit path, while the native renderer cannot choose arbitrary storage. Keep the gateway running
while reviewing newly discovered definitions; every new tool is initially withheld.
After local approval, the client's next `tools/list` returns approved tools. Every
`tools/call` performs another complete upstream listing before authorization.

Local approvals never travel over MCP. A model cannot approve, revoke or change
policy through this gateway. The local desktop bridge uses the separate
`driftguard-desktop-bridge --db /absolute/path/to/driftguard.sqlite3` entry point.
Manual imports use a distinct `import:` namespace and principal; their approvals
cannot authorize a live transport connection. For normal protection, review the catalog that
the running gateway discovers directly.

Standard output carries JSON-RPC only. Diagnostic messages use standard error and
do not print subprocess arguments, tool arguments/results, credentials or upstream
error bodies. Upstream standard error is discarded by default because it can
contain credentials or private results.

## What is enforced

1. Bind the connection to its resolved executable, argument vector, working
   directory, protocol version and passed environment. Include content digests of
   the executable and directly named file arguments in the identity fingerprint.
   Recompute the binding before discovery and immediately before sending a call.
   Bind approval additionally to a fresh random live-connection identifier, so an
   unclean gateway crash/restart cannot inherit the previous child's approvals.
   The `identity` command prints a static configuration diagnostic, not an
   execution grant or a reusable live authorization context.
2. Require complete, bounded discovery before updating the local catalog. Duplicate
   names, invalid schemas/names, oversized catalogs, repeated cursors, malformed
   JSON, nonfinite values, invalid UTF-8 and excessive nesting fail closed.
3. Require an exact definition hash and current review revision, bound to the
   configured server identity, authorization context and policy revision. The
   store holds its SQLite transaction through authorization and dispatch. Other
   database connections cannot interleave a committed revocation before dispatch.
4. Refresh definitions before every call. Pending, denied, revoked, quarantined,
   removed, unknown or changed tools cannot be forwarded. Review is local and
   exact; the research classifier never grants execution permission.
5. Reject unsupported protocol methods, callbacks, extensions and incomplete
   modern results. Requests cannot reach roots, prompts, resources, sampling,
   elicitation, tasks, or approval operations through an unguarded pass-through.
6. Apply an independent text-only output policy. Non-text content, resource links,
   embedded resources, malformed output, known passed credentials and PEM private
   keys are blocked. Arbitrary metadata and structured content are not forwarded.
   Tools declaring `outputSchema` are withheld and cannot be invoked by this
   profile, even after definition review, because dropping structured output would
   violate their advertised contract. Their blocked calls record
   `unsupported_output_contract` for local inspection.
7. Bound writes and responses by timeout and message size. Invalidate approvals
   on disconnect, malformed catalog, transport failure or explicit shutdown.
   Reconnection requires new local review. Failed calls are never automatically
   replayed because a timed-out upstream operation may already have had effects.

The default request frame limit is 1 MiB, catalog limit 8 MiB, tool count 1,000,
pagination limit 100 and request timeout 15 seconds. The independent GuardStore
policy may impose tighter limits. Directly bound executable/file arguments are
limited to 256 MiB in aggregate for identity hashing. Reader queues, JSON depth,
notifications and output items are also bounded. Catalog refresh includes every
page; server cache hints are not used to skip security revalidation.

The minimal inherited environment includes ordinary OS path/home/locale settings.
Additional variables must be named explicitly in `pass_env`; values are taken from
the launch environment and never written into the configuration or audit records.
Exact known-credential checks cover passed values at least eight characters long,
including tool definitions before persistence. Shorter values, transformed secrets,
and secrets obtained independently by the server are not comprehensively detected.
Use your OS credential manager or host to supply secrets. DriftGuard does not yet
provide an OS keychain integration. Changing passed environment values invalidates
the connection identity.

## Protocol implementation and limits

Verified against official primary specifications on 2026-10-15:

| Feature | This implementation |
|---|---|
| 2025-11-25 stdio | Explicit `initialize`, matching version, `notifications/initialized`, tools listing/calls |
| 2026-07-28 stdio | Per-request `params._meta` protocol version and client capabilities; modern `server/discover`; complete results with gateway serverInfo |
| Downstream compatibility | Separate explicit legacy initialization or required modern request metadata; no silent downgrade |
| List caching | Modern facade returns deterministic names, `ttlMs: 0`, `cacheScope: private`; relists before calls |
| Catalog pagination | Bounded complete upstream pagination; facade returns a single bounded approved catalog |
| Subscriptions | Unsupported; no subscription/list-change capability advertised |
| MRTR / input-required results | Rejected; no roots, sampling, elicitation or extension capability advertised |
| Request cancellation | Calls are serialized and time-bounded; concurrent cancellation is not implemented |
| Streamable HTTP | **Not implemented**; no HTTP compatibility claim |
| JSON Schema | Core validates definition schemas against supported JSON Schema 2020-12 metaschema; argument/output instance validation and external `$ref` resolution are not implemented; outputSchema tools are withheld |
| Platform validation | Authored subprocess tests run on Linux here; macOS/Windows runtime validation remains pending |

This is a restricted interoperable tools subset, **not full MCP conformance**.
Modern MCP additionally requires subscription/MRTR mechanics and schema support
that remain work items. In particular, modern HTTP requires per-request metadata
mirrored into `MCP-Protocol-Version`, `Mcp-Method` and `Mcp-Name` headers, matching
body/header validation, schema-derived `Mcp-Param-*` headers, JSON and request-scoped
SSE responses, and changed lifecycle rules. None of these are simulated by the
stdio implementation. A later HTTP adapter also needs credential-manager/OAuth
integration, TLS validation, redirect restrictions, Origin checks and SSRF policy.

Official references:

- [2026-07-28 base protocol and request metadata](https://modelcontextprotocol.io/specification/2026-07-28/basic)
- [2026-07-28 stdio transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio)
- [2026-07-28 Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)
- [2026-07-28 tool definitions](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)
- [2026-07-28 schema reference](https://modelcontextprotocol.io/specification/2026-07-28/schema)
- [2025-11-25 lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)
- [2025-11-25 transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)

## Boundaries that remain

The subprocess executes with the launching user's permissions. This gateway is
not an OS sandbox and cannot stop an untrusted process reading files, accessing
the network or changing behavior independently. POSIX shutdown terminates the
gateway-created process group; Windows currently terminates the immediate process,
without a Job Object guarantee for descendants.

Identity digests detect changes in directly named executable/script files and
configuration; they do not attest dynamically imported modules, package trees,
remote backends or server runtime behavior. Hashing and launching are separate OS
operations, so executable replacement races are not eliminated. A malicious server
can advertise an approved definition and execute something else, or change between
listing and invocation. No standard upstream atomic definition-revision contract
is assumed. Local serialization reduces local approval races only.

Output checks are conservative heuristics. They do not detect every secret or
arbitrary prompt injection, validate truthful tool behavior, or prevent the tool's
side effects before its result is received. Text can include untrusted instructions
or URLs. MCP clients must continue treating all returned text as untrusted data.
Protect the local database and review bridge with normal user account/OS controls.
There is no cloud analysis or telemetry in this transport.

## Reproduce the integration tests

```bash
python -m pytest -q tests/test_gateway_transport.py tests/test_gateway.py
python -m ruff check src/driftguard/gateway_transport.py src/driftguard/gateway_cli.py tests/test_gateway_transport.py
```

The wire tests create and execute an authored fixture server under a temporary
directory. They never download or execute third-party MCP servers. They exercise
modern/legacy wire formats, withholding before approval, changed and revoked
definitions, policy revisions, reconnect, malformed and duplicate catalogs,
pagination loops, oversized frames, wrong response IDs, timeouts, executable-file
identity changes, output-secret checks, method restrictions and JSON-only CLI output.
