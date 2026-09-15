# DriftGuard Operator Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, test, run, and visually verify a premium GitHub-style operator dashboard for MCP DriftGuard.

**Architecture:** Package a framework-free HTML/CSS/JavaScript dashboard inside `driftguard.ui` and serve it from the optional FastAPI app. The dashboard reads only existing versioned public API contracts and subscribes to the existing SSE timeline endpoint for live updates.

**Tech Stack:** Python 3.11+, FastAPI/Starlette optional API extra, static HTML/CSS/vanilla JavaScript, pytest, Ruff, Chromium for local visual verification.

**Spec:** `docs/superpowers/specs/2026-09-15-operator-dashboard-design.md`

## Global Constraints

- Keep development on `dev/project-scaffold`.
- Do not introduce a Node build toolchain.
- Do not merge to `main`.
- Normal runtime never silently substitutes demo data; demo mode requires `?demo=1`.
- UI consumes API read models and SSE; it does not access storage internals.

---

### Task 1: Dashboard route and package assets

**Files:**
- Create: `src/driftguard/ui/__init__.py`
- Create: `src/driftguard/ui/index.html`
- Create: `src/driftguard/ui/styles.css`
- Create: `src/driftguard/ui/app.js`
- Modify: `src/driftguard/api.py`
- Modify: `pyproject.toml`
- Test: `tests/test_ui.py`

**Interfaces:**
- Consumes: FastAPI `create_app(...)`.
- Produces: `GET /`, `GET /ui/styles.css`, `GET /ui/app.js`.

- [ ] **Step 1:** Add failing tests asserting the dashboard route and packaged assets exist.
- [ ] **Step 2:** Run `pytest -q tests/test_ui.py` and confirm route/asset failures.
- [ ] **Step 3:** Add UI package assets and FastAPI routes using `importlib.resources`.
- [ ] **Step 4:** Run `pytest -q tests/test_ui.py` and confirm pass.
- [ ] **Step 5:** Commit `feat: add DriftGuard operator dashboard shell`.

### Task 2: Repository overview UI

**Files:**
- Modify: `src/driftguard/ui/index.html`
- Modify: `src/driftguard/ui/styles.css`
- Modify: `src/driftguard/ui/app.js`
- Test: `tests/test_ui.py`

**Interfaces:**
- Consumes: `GET /v1/servers/{server}/overview`, `/status`, `/checkpoints`.
- Produces: overview headline, summary cards, checkpoint divergence, tool-state summary.

- [ ] **Step 1:** Extend HTML tests for semantic landmarks and required component IDs.
- [ ] **Step 2:** Run the focused UI test and confirm the new assertions fail.
- [ ] **Step 3:** Implement overview rendering, loading/error states, and explicit demo-mode seed data.
- [ ] **Step 4:** Run focused UI tests.
- [ ] **Step 5:** Commit `feat: build repository overview dashboard`.

### Task 3: Revision history and detail inspector

**Files:**
- Modify: `src/driftguard/ui/index.html`
- Modify: `src/driftguard/ui/styles.css`
- Modify: `src/driftguard/ui/app.js`
- Test: `tests/test_ui.py`

**Interfaces:**
- Consumes: `/revisions`, `/revisions/{revision}/view`, `/checks`.
- Produces: revision list and inspector with JSON-pointer field diffs/security check.

- [ ] **Step 1:** Add failing markup assertions for revision list/inspector/dialog accessibility.
- [ ] **Step 2:** Run focused test and confirm failure.
- [ ] **Step 3:** Implement revision rows, state badges, selection, detail rendering, field-level diff.
- [ ] **Step 4:** Run focused tests.
- [ ] **Step 5:** Commit `feat: add revision history inspector`.

### Task 4: Live activity timeline

**Files:**
- Modify: `src/driftguard/ui/index.html`
- Modify: `src/driftguard/ui/styles.css`
- Modify: `src/driftguard/ui/app.js`
- Test: `tests/test_ui.py`

**Interfaces:**
- Consumes: `/timeline` and SSE `/events`.
- Produces: live timeline, connection/reconnect state, event deduplication.

- [ ] **Step 1:** Add failing tests for timeline/live status elements.
- [ ] **Step 2:** Run focused UI tests and confirm failure.
- [ ] **Step 3:** Implement initial timeline fetch and EventSource subscription/reconnect.
- [ ] **Step 4:** Run focused tests.
- [ ] **Step 5:** Commit `feat: stream live DriftGuard activity in dashboard`.

### Task 5: Visual polish, responsiveness, and accessibility

**Files:**
- Modify: `src/driftguard/ui/styles.css`
- Modify: `src/driftguard/ui/index.html`
- Modify: `src/driftguard/ui/app.js`

**Interfaces:**
- Produces: desktop/tablet/mobile visual system with keyboard/focus support.

- [ ] **Step 1:** Define responsive breakpoints and accessible focus/status semantics.
- [ ] **Step 2:** Implement premium dark visual system and responsive layout.
- [ ] **Step 3:** Run `ruff check .` and `pytest -q tests/test_ui.py tests/test_api_smoke.py`.
- [ ] **Step 4:** Commit `style: polish DriftGuard operator dashboard`.

### Task 6: Full verification and screenshots

**Files:**
- Modify if needed only for verified defects.
- Output screenshots under local test artifacts; do not commit generated screenshots unless intentionally documented.

**Interfaces:**
- Consumes: complete repository and dashboard.
- Produces: verified test results and screenshots.

- [ ] **Step 1:** Run full `pytest -q`.
- [ ] **Step 2:** Run `ruff check .`.
- [ ] **Step 3:** Verify GitHub Actions core, ML, and API jobs.
- [ ] **Step 4:** Launch FastAPI locally with seeded demo state.
- [ ] **Step 5:** Open the dashboard in Chromium at desktop and mobile viewport sizes.
- [ ] **Step 6:** Verify no console/runtime errors and exercise revision selection/navigation.
- [ ] **Step 7:** Capture overview, revision inspector, and mobile screenshots.
- [ ] **Step 8:** Commit any final verified fixes and rerun the relevant verification commands.
