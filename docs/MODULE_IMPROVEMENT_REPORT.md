# DriftGuard module improvement report

This report groups source files by the jobs users and maintainers perform. The Rust desktop is the product target, and the Python research and compatibility paths have their own recommendations. Each section pairs the current behavior with four proposed improvements. The proposals are backlog items.

## 1. Harness setup and configuration

**Code** · [harness.rs](../rust-version/src/harness.rs), [harness_config.rs](../rust-version/src/harness_config.rs), [workspace.rs](../rust-version/src/workspace.rs), [LiveConnection.tsx](../desktop/src/LiveConnection.tsx)

The app writes reversible client entries and checks whether the gateway attaches. Desktop setup defaults to a sample unless a trusted profile is supplied.

1. **Connection doctor.** Show configuration saved, client attached, upstream reachable, and tool call verified as separate steps, each with its own last result.//
2. **Managed setup for an existing MCP.** Let users select a supported configured server, preview the routing change, and verify the managed route with discovery. Keep account authentication in the client where appropriate.//
3. **Project-aware setup.** Show user and project entries together with precedence and the exact config file DriftGuard will update. Treat two projects with different bindings as distinct routes.//
4. **Repair changed entries.** Show the differences between the saved managed entry and the current file. Offer an explicit repair that preserves unrelated user edits and produces a recovery receipt.

## 2. Discovery and connector inventory

**Code** · [harness_catalog.rs](../rust-version/src/harness_catalog.rs), [codex_catalog.rs](../rust-version/src/codex_catalog.rs), [catalog-connections.ts](../desktop/src/catalog-connections.ts), [host_catalog.py](../src/driftguard/host_catalog.py)

Rust can discover Codex runtime connectors and group them by name. Catalog errors tell the user what happened during a scan, and observed definitions are retained separately.

1. **Persistent connector health.** Store the last scan attempt, last successful result, and current status per connector. Distinguish an empty tool list, sign-in required, timeout, and stale cached results. //
2. **Retry one source.** Refresh GitHub or Canva individually and show progress per row. A slow catalog should leave successful results visible immediately. //
3. **Reconcile removals after complete scans.** Mark a connector or tool as retired after a complete authoritative inventory confirms its removal. Keep its historical records and show stale observations after partial failures.
4. **Show scope beside each connector.** Identify whether it came from the harness runtime, user configuration, project configuration, or a managed route. Link to the applicable setup or review action.

## 3. MCP transport, schemas, and credentials

**Code** · [discovery.rs](../rust-version/src/discovery.rs), [http.rs](../rust-version/src/http.rs), [contracts.rs](../rust-version/src/contracts.rs), [credentials.rs](../rust-version/src/credentials.rs), [input.rs](../rust-version/src/input.rs)

The transport supports stdio and configured Streamable HTTP. It validates inputs against supported contracts and keeps credentials at the local engine boundary.

1. **Actionable connection diagnostics.** Distinguish command launch, handshake, credential, schema, and network failures using safe reason codes and component-level timings.
2. **Authentication status and reauthorization.** Surface expired or missing credentials and guide users to the relevant client sign-in or endpoint-bound credential flow. Verify success through discovery before reporting the connection healthy.
3. **Contract compatibility inspector.** Point to the unsupported schema path or field and preview valid inputs using local validation. Keep validation and execution separate.
4. **Reconnect and cancellation tests by transport.** Exercise stream interruption, timeout, duplicate delivery, and cancellation uncertainty. Retry discovery where safe and keep tool invocations single-attempt by default.

## 4. Gateway enforcement and steering

**Code** · [gateway.rs](../rust-version/src/gateway.rs), [review.rs](../rust-version/src/review.rs), [schema.sql](../rust-version/src/schema.sql)

The gateway rechecks tool identity and version, exposes approved tools, and enforces tool and server blocks. Sentinel records admission and the final gateway outcome.

1. **Show pending, admitted, and upstream outcomes separately.** Record the handoff boundary and display “outcome unknown” when the connection closes before a result. Include stable receipt IDs in denials where possible.
2. **Show the impact of Stop.** Preview affected routes and calls already admitted. Report cancellation requests separately from any transport-confirmed outcomes.
3. **Version-bound policy exceptions.** Allow an owner to create a narrow exception by route, tool version, and duration. Show when it expires and keep explicit server stops and denials authoritative.
4. **Verify steering with real clients.** Exercise cached tool lists and list-change support in each harness. Show the capability of the connected client in the UI and verify call-time enforcement independently.

## 5. Review, baselines, and history

**Code** · [review.rs](../rust-version/src/review.rs), [ReviewPanel.tsx](../desktop/src/ReviewPanel.tsx), [Timeline.tsx](../desktop/src/Timeline.tsx), [ToolCatalog.tsx](../desktop/src/ToolCatalog.tsx), [diff.py](../src/driftguard/diff.py)

The desktop compares definitions and preserves version history. The Rust review now uses the first recorded definition as the comparison baseline until an explicit approved baseline exists.

1. **Choose two versions to compare.** Offer initial observation, approved baseline, last successful call, and any two historical versions. Preserve the timestamps and version hashes in the comparison.
2. **Summarize meaningful field changes.** Put description, required arguments, defaults, output shape, and claimed permissions first. Link each summary to the exact field.
3. **Group reviews by cause.** Use one queue entry for a catalog refresh, with separate review decisions for each affected managed tool. Keep ordinary edits in history and reserve the new-connection notice for discovery.
4. **Handle retirement and reappearance explicitly.** Show when a tool was withdrawn, returned, or was rebound to a different source identity, with the previous evidence still accessible.

## 6. Live graph and Time Machine

**Code** · [ConnectionGraph.tsx](../desktop/src/ConnectionGraph.tsx), [Sentinel.tsx](../desktop/src/Sentinel.tsx), [review.rs](../rust-version/src/review.rs)

The graph shows managed activity and catalog topology. The Time Machine reads recent call records in pages and compares selected evidence with policy.

1. **Filter across stored history.** Move route, session, time, tool, and outcome filters into the indexed query so the displayed count includes older matching records.
2. **Inspect the graph at a point in time.** Pin a call or timestamp and reconstruct the route, known tool versions, and recorded policy state for that point. Show when historical evidence is missing.
3. **Explain what changed since the last success.** Place tool edits, stops, approval changes, and helper changes between the two calls. Separate recorded causes from changes that may be related.
4. **Live-follow and pause.** Show new activity while following the live edge and keep the selection and scroll position fixed when investigating an older call.

## 7. Adaptive privacy and privacy history

**Code** · [gateway.rs](../rust-version/src/gateway.rs), [contracts.rs](../rust-version/src/contracts.rs), [Sentinel.tsx](../desktop/src/Sentinel.tsx)

Sentinel fingerprints selected structured values within a gateway connection and keeps raw call arguments and results out of its ledger.

1. **Destination-aware approvals.** Bind any privacy exception to an observed destination, tool version, session, and expiry. Show the destination category before granting an exception.
2. **Correlate across verified sessions.** Combine privacy evidence from multiple managed routes only when a trusted host can establish their common work session. Preserve the individual route identity in every decision.
3. **Explain the evidence and outcome.** Show the category, source call, and destination when available. Distinguish prevention before dispatch, withheld output, and uncertain upstream outcome.
4. **User-controlled retention.** Expose retention duration, ledger disk use, and history clearing in Settings. Keep security decisions and diagnostic call records separately selectable.

## 8. Harness helper tracking

**Code** · [harness_helpers.rs](../rust-version/src/harness_helpers.rs), [HarnessHelpers.tsx](../desktop/src/HarnessHelpers.tsx)

The scanner inventories supported user-level helper files and records fingerprint changes without executing their contents.

1. **Track selected project roots.** Include repository instructions, skills, commands, and hook files for projects the user adds. Display where project and user settings overlap.
2. **Explain what changed without revealing commands.** For parsed files, show safe summaries such as plugin toggled, hook added, or permission rule count changed. Keep helper contents out of stored reports.
3. **Link helpers to known-good setups.** Save a workspace snapshot and compare two dates or two harnesses. Use the result to reproduce setup differences across machines.
4. **Improve incomplete-scan handling.** Show paths skipped because of unreadable files, unsupported layouts, or bounds. Keep the last successful observation and give each warning a useful recovery action.

## 9. Models and automatic decisions

**Code** · [decision_model.rs](../rust-version/src/decision_model.rs), [semantic_xgboost.py](../src/driftguard/semantic_xgboost.py), [tree_learning.py](../src/driftguard/tree_learning.py), [temporal.py](../src/driftguard/temporal.py)

The Rust path can use a local logistic policy. Python can compare structured and semantic features offline. Human-labeled external validation is still a research gap.

1. **Run candidates in shadow mode.** Record hypothetical decisions without changing execution. Compare with existing policy and review outcomes before promoting a model.
2. **Build a model evidence view.** Show model version, evidence, threshold band, and reason for abstaining. Keep authorizations explainable by exact version and policy.
3. **Measure the cost of interventions.** Evaluate false quarantines, missed risky changes, human overrides, and review workload at each threshold. Report legitimate capability expansions separately.
4. **Require held-out gains for heavier models.** Add XGBoost or MiniLM to live scoring only after a measured benefit on unseen repositories, with regression checks for latency and memory.

## 10. Research laboratory and reproducibility

**Code** · [AnnotationLab.tsx](../desktop/src/AnnotationLab.tsx), [annotation_workflow.py](../src/driftguard/annotation_workflow.py), [splits.py](../src/driftguard/splits.py), [experiments](../experiments)

The annotation and benchmarking pipeline exists. The handoff records 494 unlabeled primary candidates and 227 separate reference records.

1. **Save and resume annotation sessions.** Persist local progress and validate exports before they leave the app. Preserve independent annotator identities and provenance.
2. **Add adjudication and disagreement views.** Compare blinded exports and show ambiguous C2/C3 cases with the source evidence both annotators used.
3. **Freeze a reproducible benchmark bundle.** Publish eligible source and split hashes, exclusions, feature definitions, and exact commands. Keep private records out of public artifacts.
4. **Generate one result table across baselines.** Include grouped confidence intervals, false intervention rates, detection delay, calibration, and a representative failure analysis.

## 11. Python compatibility and engine parity

**Code** · [desktop_bridge.py](../src/driftguard/desktop_bridge.py), [gateway.py](../src/driftguard/gateway.py), [gateway_transport.py](../src/driftguard/gateway_transport.py), [managed_harnesses.py](../src/driftguard/managed_harnesses.py)

Python supports the research pipeline and a separate desktop/runtime path. Rust exposes Sentinel and newer discovery behavior.

1. **Publish a capability matrix.** Label which engine supports each desktop action, harness integration, transport, and policy behavior. Use runtime capabilities to hide actions that the selected engine cannot serve.
2. **Use shared contract fixtures.** Compare exact hashes, migration behavior, denied outcomes, and catalog handling on both engines from the same input fixtures.
3. **Support a review-evidence migration.** Offer a dry-run import of historical definitions and labels. Identify conflicts and require fresh session-bound approval for managed calls.
4. **Keep a single desktop regression contract.** Run the same setup, review, filters, and failure-flow browser tests against both backends where their features overlap.

## 12. Desktop shell, packaging, and performance

**Code** · [App.tsx](../desktop/src/App.tsx), [native bridge](../desktop/src-tauri/src/lib.rs), [desktop validation workflow](../.github/workflows/desktop-validation.yml), [Rust benchmark](../rust-version/benchmark.py)

The renderer uses bounded native IPC, a packaged sidecar, and automated browser and startup tests. Some overview data is refreshed in separate requests.

1. **Keep navigation and recovery visible.** Preserve selected tool and graph filters across routes and expose one accessible place to find connector, helper, and gateway health.
2. **Reduce idle polling overhead.** Coalesce graph, activity, and catalog revision reads. Benchmark the full desktop and drive refresh from changes where practical.
3. **Publish native Rust compatibility results.** Verify installer startup, sidecar location, keyboard interaction, accessibility, and configuration repair on each advertised OS.
4. **Prepare a production update path.** Sign builds, verify installer and sidecar provenance, and test database upgrades and recovery from an interrupted update.

## Suggested order

1. **Make current behavior easy to trust.** Ship the connection doctor, persistent source health, source-specific retries, and server-side Time Machine filters.
2. **Make failures explainable.** Add last-success comparisons and a durable distinction between admitted calls and known upstream outcomes.
3. **Strengthen setup and recovery.** Add a managed setup preview, project scope and reconciliation, plus transport-specific cancellation verification.
4. **Evaluate automation before expanding it.** Finish independent annotation, run shadow scoring, and promote policies only with measured benefits.
