# DriftGuard Operator Dashboard Design

## Goal

Build a polished, demo-ready web interface for MCP DriftGuard that feels like GitHub Security, Linear, and Codex while remaining Python-first and dependency-light.

## Product model

The dashboard is a repository browser for an MCP server. It should make five questions answerable within seconds:

1. What is the current MCP tool surface?
2. What changed since the previous revision?
3. What changed since the last trusted checkpoint?
4. What security verdict did DriftGuard make?
5. What happened over time and who reviewed it?

## Architecture

The UI is served directly by the optional FastAPI control plane. It uses static HTML/CSS/JavaScript packaged with the Python distribution; no Node, React, Vite, or separate frontend deployment is required.

The UI consumes existing DriftGuard APIs:

- `/v1/servers/{server}/overview`
- `/v1/servers/{server}/status`
- `/v1/servers/{server}/revisions`
- `/v1/servers/{server}/timeline`
- `/v1/servers/{server}/checkpoints`
- `/v1/servers/{server}/checks`
- `/v1/servers/{server}/revisions/{revision}/view`
- `/v1/servers/{server}/events` for live SSE updates.

## Visual direction

- Deep graphite background with subtle radial gradients.
- High-contrast white/gray typography with monospace metadata.
- Emerald for pass/trusted, amber for review/pending, red for blocked/quarantine.
- Thin borders, layered translucent panels, low-radius cards, restrained shadows.
- Dense enough for engineers, but with clear hierarchy and large headline status.
- Sidebar navigation inspired by GitHub repositories.
- Top command/search bar inspired by developer tools.
- Activity and revision UI inspired by commit history and security checks.

## Primary screen

The landing dashboard contains:

- left navigation rail,
- server selector and live connection indicator,
- headline security state,
- four summary metrics,
- checkpoint divergence card,
- tool-surface summary,
- recent revisions table,
- live activity timeline,
- revision inspector drawer/panel.

## Revision inspector

Selecting a revision shows:

- revision/tree IDs,
- provenance channel and trigger,
- exact field-level JSON-pointer diff,
- persisted security check,
- per-tool risk score and class,
- freshness state for latest revision,
- checkpoint distance where relevant.

## Empty/loading/error states

The UI must remain useful when:

- no server data exists,
- an endpoint returns 404,
- SSE reconnects,
- a checkpoint has not been created,
- a revision has no persisted security check.

The dashboard may use demo seed data only when explicitly opened with `?demo=1`; normal runtime never silently substitutes demo data.

## Responsiveness

- Desktop: three-column composition with persistent sidebar and detail panel.
- Tablet: detail panel becomes an overlay drawer.
- Mobile: sidebar collapses; cards stack; revision table becomes compact cards.

## Accessibility

- Keyboard-visible focus states.
- Semantic buttons and links.
- Status is communicated by text/icon as well as color.
- Minimum readable contrast on dark theme.

## Testing

- API smoke test verifies dashboard routes/static assets exist.
- Static HTML test verifies core accessibility/landmark IDs and script/style references.
- JavaScript remains framework-free and should fail gracefully when APIs are unavailable.
- Full Python, API, and ML CI must remain green.

## Constraints

- Keep development on `dev/project-scaffold`.
- Do not introduce a Node build toolchain.
- Do not merge to `main`.
- Preserve the research/runtime architecture; UI depends on public read models rather than reaching into storage internals.
