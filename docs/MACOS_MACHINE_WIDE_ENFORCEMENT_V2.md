# DriftGuard 2.0 — Machine-wide macOS enforcement architecture

**Status:** Architecture proposal; no endpoint or network system extension has been implemented.
**Baseline:** `rust-macos-preview` (existing Rust tool gateway, review/quarantine engine, Codex managed policy and separate desktop workspace).
**Target:** Apple silicon and Intel macOS machines supported by a signed, notarized native distribution.
**Security principle:** Never say "protected" without an enforceable path and a successful denial test.

## 1. Precisely define machine-wide

Two distinct product claims must not be conflated:

1. **Machine-wide OS guardrails:** a privileged, OS-approved system extension can enforce process/file or network restrictions across user sessions, regardless of which desktop UI is open.
2. **Machine-wide MCP invocation mediation:** every actual MCP `tools/call` is inspected and authorized. This is **not** attainable for arbitrary existing applications merely by installing an extension. A client can call private/in-process tools; stdio can run inside interpreters; remote MCP over encrypted HTTPS cannot be identified reliably from socket metadata.

The proposed product combines (1) with an authenticated MCP broker and a **managed, constrained agent execution mode**. Only state the stronger tool-level guarantee for explicitly enrolled processes/sessions whose possible bypass routes have been blocked or isolated and then tested. Treat other processes as **observed**, **restricted**, **outside scope**, or **unverified**, never silently protected.

The existing Codex system policy is an interim harness-specific protection; it does not make the Mac a universal MCP firewall. The administrator-owned gateway and desktop store remain independent until intentionally unified.

## 2. Trust and threat model

- **Trusted:** macOS kernel, System Integrity Protection, Apple code-signing and entitlements, the installed system extensions, broker binary, local signed policy, and a Mac administrator who controls enrollment.
- **Adversarial:** untrusted MCP definitions, direct remote MCP endpoints, local stdio server binaries and scripts, tool output, malicious catalog drift, untrusted model-generated shell commands, and ordinary-user applications attempting to bypass enrolled policy.
- **Out of guarantee:** the system administrator/root intentionally turning protection off; a compromised kernel; remote model-provider hosted tools that never run through this Mac; arbitrary browser/cloud actions masquerading as non-MCP traffic; encrypted payloads for which endpoints are not enrolled; TCC/SIP-bypass claims.
- **Privileged deployment:** require official Apple approval for Endpoint Security entitlement and supported Network Extension entitlement; Developer ID and notarization for distribution. Do **not** ask users to turn off SIP for a production build. Apple's development-only workarounds are not acceptable release steps.

## 3. Components and authority

### A. DriftGuard Core / Rust MCP broker — reuse existing work

Keep exact definition SHA256+revision approval, shared block, quarantine, activity, version history and optional privacy lineage. Every enrolled upstream connection is brokered. The broker dispatches only after authorization, revalidates tool definition freshness, validates args/results and emits audit events. Local stdio and HTTPS remote MCP are supported through explicitly registered profiles.

Run the broker as a dedicated least-privileged launchd service, e.g. `_driftguard`, not as root. Avoid putting raw credentials or tool contents in global logs. Existing per-user desktop review databases must be migrated deliberately to the authoritative machine policy store or clearly displayed as read-only snapshots.

### B. Privileged policy coordinator

A minimal launchd-owned coordinator installs, updates and rolls back OS extensions and publishes short-lived, signed/verified policy snapshots to their providers. Expose narrowly scoped XPC operations with audit-token, code-signature, Team ID and caller identity validation. Do not trust claimed PID, string client name, or user-provided filesystem paths alone. Administrator authorization is needed for activation, policy mode changes and extension removal. End-user manual tool review must be explicitly bound to their role.

Protect policy state, keep monotonic revisions, use atomic writes, and store secrets in Keychain under endpoint-specific identities. Keep the agent's chat text and tool arguments out of ES and network telemetry.

### C. Endpoint Security system extension (ES)

Use Apple's EndpointSecurity `AUTH_EXEC` and relevant supported file authorization events to constrain **enrolled agent processes and descendants**. Monitor process ancestry, signed executable identity, argument metadata where available, selected script paths and protected file changes to support provenance; do not infer an MCP call merely from a `node` or `python` process name.

- For supervised/managed agent sessions, reject spawning unauthorized MCP server binaries, interpreters with prohibited scripts, and unapproved direct helper processes.
- Enforce sensitive-file access policy independently of MCP tool names where the authorization API permits.
- Cache locally compiled policy decisions. Never wait for an LLM/network response inside an ES authorization deadline.
- Explicitly test reparenting, PID reuse, symlinks, interpreter invocation, app bundle updates, file descriptor inheritance and process-start races.

An ES authorization event cannot semantically recognize an arbitrary in-process tool call; interpreter/file access coverage must be measured rather than assumed.

### D. Network Extension content filter (NE)

Use a macOS Network Extension content filter (e.g., `NEFilterDataProvider` + `NEFilterControlProvider`) to decide whether to allow or block connections based on process identity, signed application provenance, endpoint/port and a compiled allow/deny policy. Where supported, use flow audit tokens for source attribution.

- For enrolled agent processes and descendants: deny direct external MCP-capable connections unless explicitly authorized, brokered or on a tightly tested allowlist. Provide a separate allowed route for essential model-provider/API dependencies to avoid breaking all client functions.
- Cover IPv4, IPv6, TCP, UDP/QUIC, remote DNS and loopback/Unix-socket bypass scenarios separately. Network Extension does not automatically inspect Unix-domain sockets or every local IPC mechanism.
- Avoid blanket TLS man-in-the-middle interception, root certificates, or misleading path-level HTTPS claims. Encrypted payloads normally cannot be interpreted as MCP by a content filter.
- A data filter should return bounded local verdicts, with configuration communicated through the supported control-provider mechanism; it is not a general-purpose IPC/network client.

Apple currently documents macOS system-extension content filters, but signing, authorization and distribution rules must be validated on an **ordinary unmanaged personal Mac** and on an MDM-managed Mac before shipping. Interpret `NEFilterManager` documentation alongside platform-specific TN3134, not by assuming iOS supervision rules apply identically to macOS.

### E. Strong managed-agent runtime (needed for meaningful guarantees)

Offer **Protected Agent Mode** in which supported harnesses run with enforceable restrictions on child processes, network egress, local filesystem access and tool registration. Prefer supported OS sandbox mechanisms and/or an isolated VM-based runner where an ordinary process cannot be constrained sufficiently. A generic Mac-global network filter cannot tell whether arbitrary HTTPS is an MCP call; an isolated agent with only broker-approved egress provides an auditable security boundary.

Direct third-party apps without cooperation can be covered by OS-level connection/process restrictions, but cannot be labelled "every MCP tool call inspected" unless the bypass test proves all relevant paths are constrained. For uncooperative programs, optionally require explicit admin enrollment and full network/exec restrictions that may affect ordinary application functions.

## 4. Example call and bypass decision

```
Enrolled client wants MCP tool
  -> authenticated local broker session
  -> trusted server registration + full tool catalog
  -> exact-version policy + capability / privacy check
  -> allow / deny / quarantine / prompt (outside OS auth hot path)
  -> broker executes or refuses, appends auditable decision

Enrolled client tries direct executable / connection
  -> ES or NE checks compiled process/egress policy
  -> allow only an independently approved dependency
  -> otherwise deny and record blocked bypass attempt

Unknown app / unclassified encrypted traffic
  -> apply configured machine-wide network rule if suitable
  -> show "unverified" or "outside coverage" for MCP semantics
  -> never claim invocation-level inspection
```

## 5. Enforcement levels surfaced in the UI

| Mode | Included guarantee | Excluded |
| --- | --- | --- |
| Review only | Catalog inspection and manual decisions | Live interception |
| Routed MCP | Exact tool-level gate for brokered connections | Direct connections |
| System guardrails | OS process/flow blocks for configured scope | Semantic inspection of opaque/in-process calls |
| Protected Agent | Brokered MCP, denied direct egress/execution with verified containment | Host/cloud actions outside enrolled runtime |
| Managed-device policy | Administratively enrolled multi-user restrictions, subject to Apple deployment policy | Malicious administrator, compromised OS |

Show per-process coverage, status of ES/NE extensions and their permissions, current policy revision, recorded bypasses, and a measured **coverage report**, not a global green shield with unsupported claims.

## 6. Delivery phases and hard gates

**Phase 0 — feasibility, signing, and threat model.**
Prove Apple entitlements, System Extension activation and Network Extension filter on the intended macOS versions, starting with a Developer-ID-signed notarizable minimal extension. Verify on personal, non-MDM Mac and a managed test machine. Do not proceed if entitlements or supported deployment model cannot be obtained.

**Phase 1 — single authoritative broker and policy.**
Unify admin-managed and desktop status without silently merging incompatible approval data; implement authenticated XPC and machine-scoped policy, reliable native installer + full rollback + repair, per-user approval controls. Test Codex CLI and desktop, Claude Code and at least one other agent. Every managed call must be fail-closed if broker/policy unavailable.

**Phase 2 — Endpoint Security proof of enforcement.**
Implement a signed ES extension with minimal `AUTH_EXEC` policy and targeted file authorization. Demonstrate that blocked direct stdio MCP server launches cannot execute from a protected agent, including interpreter and process-tree variants. Keep latency bounded and do not block unrelated Mac applications by default.

**Phase 3 — Network Extension egress boundary.**
Develop an on-device filter with per-process audit-token attribution, an explicit allowlist and denied direct remote MCP attempts. Test local loopback, IPv4/IPv6, QUIC, DNS alternatives, proxy chains and crash/restart. Do not claim content inspection inside opaque TLS.

**Phase 4 — contained agent / VM mode.**
Run enrolled agents with all network and child-process exits constrained to broker-approved paths; define escape and recovery tests. Maintain a supported "compatibility mode" with transparent coverage gaps for apps that cannot be enrolled.

**Phase 5 — product readiness.**
Show per-process coverage graph, denied bypasses, policy trace, emergency disable/uninstall, rollback health, and multi-user behavior. Produce signed and notarized universal app and extension binaries; never rely on ad-hoc signing or disabling SIP in production.

**Release gates:** (a) all supported macOS platforms sign and load the extensions, (b) no unexpected direct exit from a protected agent, (c) blocked tools stay blocked during policy update, app restart, daemon restart and offline mode, (d) no permanent lockouts, (e) normal model APIs and development workflows are usable, (f) negative controls distinguish unverified from denied, (g) reproducible performance measurements exist.

## 7. Security regression matrix

Run each case on both an Apple silicon and an Intel Mac if both architectures are claimed:

- Codex CLI/desktop, Claude Code, Cursor/OpenCode and a custom MCP client: routed call allowed, blocked, quarantined, restored.
- Direct MCP over stdio: `node`/`npx`, Python, shell script, renamed binary, nested script and inherited file descriptors.
- Direct remote MCP: HTTPS, IPv4 and IPv6, localhost, alternate ports, proxy/tunnel, custom DNS, QUIC/UDP, preexisting connections before policy enable.
- Bypass tests: same-code-signing-ID descendant, process reparenting, PID recycling, malicious local process, disabled extension, broker crash, Keychain locked, system sleep/wake, multiple user sessions.
- Restore fidelity: comments/other MCP entries preserved, atomic rollback, no credentials logged, policy restore after crash/reboot.
- Developer experience: build `npm`, `cargo`, git and legitimate model requests while protected; avoid false positive denial of ordinary compiler workers.
- Rate and overhead: record median/p95/p99 native ES decision delay, filter verdict delay, user-visible tool latency, CPU and memory. Establish thresholds from measured baselines; fail CI on meaningful regressions.

The *pass condition* is a real denied OS operation or gateway refusal with independent evidence, not assistant text saying it was denied.

## 8. Explicit non-goals and dependencies

- A universal machine-wide guarantee for **every MCP invocation by every unmodified program** is not achievable with the cited OS APIs alone.
- Do not silently install certificates or MITM HTTPS. Do not turn off SIP, alter protected system services, or use undocumented kernel hooks.
- Do not replace the MCP review engine with a generic firewall; the firewall is a **complementary bypass-prevention layer**.
- Request the Apple Endpoint Security entitlement, configure Network Extension capability, activate System Extensions with administrator approval, and obtain Developer ID/notarization before broad release.

## Apple references

- https://developer.apple.com/documentation/endpointsecurity
- https://developer.apple.com/documentation/networkextension/content-filter-providers
- https://developer.apple.com/documentation/technotes/tn3134-network-extension-provider-deployment
- https://developer.apple.com/documentation/networkextension/nefilterflow/sourceappaudittoken
- https://developer.apple.com/documentation/systemextensions/
- https://developer.apple.com/system-extensions/
- https://developer.apple.com/videos/play/wwdc2025/234/
