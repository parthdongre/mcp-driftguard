# Hosted apps and local MCP servers

The apps installed in ChatGPT/Codex are not the same inventory as MCP servers in
`~/.codex/config.toml`. Some plugins expose skills, some expose tools, and some
installed entries expose no callable tools to a particular session. A local CLI
scan cannot enumerate an arbitrary hosted session or borrow its authentication.

## Inspect hosted descriptions

1. Obtain a `driftguard-host-catalog-v1` export from the authorized host session.
2. Open **MCP connections → ChatGPT / Codex installed apps**.
3. Choose the JSON catalog, inspect the preview, and save it to the workspace.
4. Expand an app and tool to read descriptions. Search matches names and text.

This is an explicit snapshot import. It does not synchronize future host changes,
connect provider accounts, fetch user data, call provider tools, copy credentials
or modify existing harness configuration. Regenerate and import a fresh snapshot
to compare later descriptions. File structure validation is not proof that the
file came from the claimed host.

The format contains app identifiers, names, descriptions, capture times,
visibility (`session_tools`, `skills_only`, `not_exposed`) and tool name/description
pairs. It deliberately does not claim to contain raw MCP input/output schemas.
The native bridge constructs an explicitly marked unknown input-contract record
for inspection, and rejects attempts to authorize execution for the
`host-metadata-review-only` principal, even after a review approval.

Hosted source metadata survives app restart, including entries without tools.
The `host:` namespace is separate from local gateway and manually imported
identities. Each app import is atomic, bounded to 500 tools, and validates all
definitions before changing the store. The UI accepts a 16-MiB catalog and sends
bounded per-app requests to the native bridge.

## Local discovery fixes

Local MCP collection has a 90-second operation budget with a 105-second native
outer deadline. It uses a separate discovery lock so reviews retain their normal
20-second deadline and do not queue behind long discovery. A concurrent second
fetch is rejected immediately instead of entering a long queue.

Codex rows with no tools, no advertised tool capability and no catalog are not
counted as successful catalogs. A genuinely empty complete tool catalog is
reported as empty, not as successful collection; existing removed definitions are
still revoked and the workspace refreshes. Partial results identify incomplete
discovery, and the UI shows elapsed time while fetching.

Native GUI, browser layout and credential-dependent integrations need validation
on their intended hosts. Tests use isolated configuration, protocol fixtures and
an optional installed Codex CLI; hosted metadata imports do not establish live
provider connectivity.

Source development also prefers the explicitly verified virtual-environment
engine over any older bundled engine left in a development resource directory.
Release builds continue to ignore the development override and require their
fixed packaged engine. This prevents a new renderer from silently calling stale
Python bridge actions during development.
