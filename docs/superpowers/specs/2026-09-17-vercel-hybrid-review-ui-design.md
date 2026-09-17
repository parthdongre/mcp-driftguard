# MCP DriftGuard — Vercel Hybrid Review UI Design

Date: 2026-09-17
Status: Design approved in principle; implementation pending written-spec review
Owner: Parth Dongre

## 1. Goal

Replace the CLI-first midsem presentation surface with a hosted Vercel web application that is visually restrained, immediately understandable in a project review, and still useful as a genuine security analysis interface.

The selected direction is the hybrid option:

1. The home screen opens directly into a polished, preloaded low-and-slow attack demonstration.
2. A secondary Analyze flow accepts custom MCP tool-definition versions and runs the same DriftGuard engine.
3. Research detail is available on demand, not permanently occupying the screen.

The web application must not become a generic dense dashboard. The primary product feeling should be closer to a focused developer/security instrument.

## 2. Design references and visual direction

The main visual reference is FrameVitals, especially its restrained dark editorial surface, strong typography, mono labels, thin separators, generous spacing, and low-card-count composition.

The implementation should inherit the design logic rather than literally copy every component:

- near-black neutral background
- warm off-white primary text
- one cool accent color
- mono labels for system/security metadata
- oversized but controlled headings
- thin 1 px borders and separators
- very limited shadows
- few rounded containers rather than a grid of many cards
- deliberate whitespace
- short motion on entry and state transitions only

Taste-skill guidance is applied contextually. This is not a landing page, so its anti-template principles matter more than its landing-page composition rules. The app should avoid generic AI-dashboard tropes: four KPI cards across the top, permanent sidebars, glassmorphism, excessive gradients, animated blobs, pill overload, or decorative charts with no security meaning.

Target design dials:

- Design variance: 5/10
- Motion intensity: 3/10
- Visual density: 3/10

The experience should feel technical but calm.

## 3. Information architecture

The application has two primary routes and one optional detail state.

### `/`

Reviewer / demo surface.

Purpose: communicate the project in under 30 seconds and support a 5–7 minute midsem demonstration.

Primary elements:

- compact top bar with DriftGuard wordmark, Research Prototype label, Analyze action, and GitHub/docs link
- short project statement
- approved baseline tool definition
- horizontal or responsive temporal lineage showing T0 through T4
- one main risk visualization containing:
  - step risk
  - approved-baseline risk
  - CUSUM / trust debt
- current policy action
- short explanation of why the current version is allowed, monitored, sent for re-consent, or quarantined
- version scrubber or Previous / Next controls for walking through the attack during the presentation
- collapsed “Why this decision?” detail section for structural/capability signals

The page should not show every research metric simultaneously.

### `/analyze`

Focused custom-analysis surface.

Purpose: prove the web app is not only a hard-coded animation.

Inputs:

- approved tool definition JSON
- one or more later tool-definition versions

Initial scope should support pasted JSON first. File upload and repository ingestion can come later.

The interaction should use a two-pane layout only on sufficiently wide screens:

- left: definitions/input
- right: analysis result

On narrower screens these become a vertical flow.

Primary action: `Analyze lineage`.

Output:

- policy result
- step and baseline risk
- CUSUM
- version lineage
- top reasons
- compact change summary

Raw feature vectors and full research diagnostics remain under an Advanced disclosure.

### Detail state

Research details should appear via a drawer, modal, or expandable region rather than a permanent third column.

This includes:

- structural delta summary
- capability escalation dimensions
- semantic drift views
- decision reasons
- threshold context

## 4. Reviewer-home interaction model

The home demo begins at the trusted baseline T0.

Example lineage:

- T0: Search repository files.
- T1: Search repository files and inspect metadata.
- T2: Search repository files, inspect metadata, and prepare results for sharing.
- T3: Search repository files, inspect metadata, and prepare results for external sharing.
- T4: Search repository files, inspect metadata, and upload results when requested.

The user can advance versions one at a time.

Each transition updates:

- selected version
- definition text
- local step risk
- approved-baseline risk
- accumulated CUSUM
- policy action
- reasons

Motion should reinforce causality. The line/risk visualization can animate between points, but no element should bounce or continuously move.

The presentation should preserve a critical distinction:

- Previous → Current shows local change.
- Approved → Current shows accumulated change from user consent.

The visual design should make these two comparisons easy to explain.

## 5. Technical architecture

### Frontend

Next.js App Router + TypeScript, deployed on Vercel.

Why Next.js:

- first-class Vercel deployment
- simple route-level architecture
- server components for static presentation shell
- route handlers/server actions for analysis requests if appropriate
- strong TypeScript and React ecosystem
- easy responsive production deployment

The UI should use lightweight custom components and CSS/Tailwind-style utility composition rather than a large dashboard framework.

Recommended frontend dependencies should stay narrow:

- Next.js
- React
- TypeScript
- Lucide icons if icons are needed
- Framer Motion only if subtle state transitions justify it

Avoid adding a charting library solely for three small temporal signals. Prefer a custom SVG risk trace to keep the visual language precise and bundle size low.

### Security engine

The existing Python `driftguard` package remains the source of truth.

Do not rewrite the detector in TypeScript.

The web layer calls a thin Python analysis endpoint that reuses:

- canonicalization
- feature extraction
- `SequentialDriftMonitor`
- risk calculation
- consent/policy logic where applicable

This prevents divergence between the research implementation and the demo application.

### API contract

Initial endpoint concept:

`POST /api/analyze`

Request:

```json
{
  "approved": { "name": "...", "description": "...", "inputSchema": {} },
  "versions": [
    { "name": "...", "description": "...", "inputSchema": {} }
  ]
}
```

Response:

```json
{
  "toolName": "search_repo",
  "approvedDescription": "Search repository files.",
  "steps": [
    {
      "version": 1,
      "description": "...",
      "stepRisk": 0.0,
      "baselineRisk": 0.0,
      "cusum": 0.0,
      "alerted": false,
      "action": "ALLOW + MONITOR",
      "reasons": []
    }
  ]
}
```

The endpoint should validate input shape and fail safely on malformed schemas.

## 6. Vercel deployment model

The preferred deployment is one Vercel project containing both the frontend and Python-backed analysis service.

Implementation should first evaluate the cleanest supported shape for the current Vercel platform:

- Next.js frontend plus Python Vercel Function, or
- a Vercel multi-service setup if required to cleanly package the existing Python project.

The architecture should not duplicate detector code merely to simplify deployment.

If the Python package cannot be packaged cleanly in a same-project function, use Vercel Services rather than converting the research core to JavaScript.

No database is required for the first version. The demo is deterministic and custom analysis can remain request-scoped.

## 7. Main components

Suggested component structure:

```text
web/
  app/
    page.tsx
    analyze/page.tsx
  components/
    Shell.tsx
    DriftHeader.tsx
    ToolBaseline.tsx
    VersionLineage.tsx
    RiskTrace.tsx
    PolicyDecision.tsx
    DecisionDetails.tsx
    AnalyzerEditor.tsx
    AnalyzerResult.tsx
  lib/
    api.ts
    types.ts
```

Backend/API placement depends on the final Vercel Python function/services choice.

The web app should live inside the existing repository so the research implementation and presentation layer remain versioned together.

## 8. Home-screen visual composition

Desktop target:

```text
┌──────────────────────────────────────────────────────────────┐
│ DriftGuard   Research Prototype                  Analyze  ↗  │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  TRUST SHOULD NOT OUTLIVE CAPABILITY.                        │
│  Detect low-and-slow MCP tool drift after approval.          │
│                                                              │
│  Approved baseline                         POLICY             │
│  Search repository files.                  QUARANTINE         │
│                                                              │
│  T0 ───── T1 ───── T2 ───── T3 ───── ● T4                  │
│                                                              │
│  RISK / TRUST DEBT                                           │
│              ───────────── custom SVG temporal trace          │
│                                                              │
│  Local step      0.xxx    Baseline       0.xxx               │
│  CUSUM           0.xxx    Approved at    T0                  │
│                                                              │
│  Why this decision?                                      +   │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

The exact copy can evolve, but hierarchy should remain this simple.

## 9. Analyzer visual composition

The analyzer should not feel like a code IDE clone.

Use a restrained editor surface with:

- clear labels for Approved and New versions
- readable mono JSON
- add-version control
- one primary Analyze button
- inline validation errors

The result side should lead with the decision, not with raw numbers.

Order:

1. decision
2. one-sentence explanation
3. temporal trace
4. reasons
5. optional advanced details

## 10. Accessibility and responsiveness

Requirements:

- keyboard-accessible controls
- visible focus states
- sufficient color contrast
- status conveyed by text/icons, not color alone
- reduced-motion support
- no hover-only essential information
- semantic headings and landmarks
- usable at 375 px width
- code editors/textareas scroll rather than causing page overflow

## 11. Honest research language

The UI must not imply production-grade attack detection accuracy.

Preferred wording:

- Research Prototype
- Controlled benchmark
- Experimental policy signal
- Reviewer demo

Avoid:

- 99% secure
- production protection
- guaranteed poisoning detection
- real-world accuracy claims unsupported by the current corpus

The demo should explicitly state that the deterministic temporal scenario illustrates the architecture and does not constitute publication-level evidence.

## 12. Testing strategy

### Python/API

- valid lineage returns deterministic analysis
- malformed schema returns 4xx
- approved baseline is preserved
- final demo trajectory reaches expected quarantine state
- endpoint output is derived from the existing detector rather than hard-coded risk numbers

### Frontend

- demo renders T0–T4
- version navigation updates visible metrics and decision
- Analyze route validates pasted JSON
- result renders returned API data
- Advanced detail is hidden by default
- responsive layout does not overflow

### End-to-end

- deployed home page loads
- reviewer can walk from T0 to T4
- custom analyzer request completes
- final action/reasons render
- no browser console errors
- primary flow works on desktop and mobile viewport

## 13. CI and deployment

Existing Python CI remains intact.

Add a web quality gate for:

- install
- TypeScript check
- frontend lint
- frontend build
- focused frontend tests

Vercel deployment should occur only after the repo is green.

The deployment should ultimately be linked from the repository README as the project demo surface.

## 14. Non-goals for this iteration

Do not add:

- authentication
- accounts
- database persistence
- telemetry dashboard
- corpus browser
- model-training UI
- repository cloning/execution from the browser
- real-time MCP proxy/interception yet
- large charting/dashboard libraries
- AI chatbot

These would distract from the midsem story and increase surface area without improving the core research demonstration.

## 15. Definition of done

This iteration is successful when:

1. Opening the Vercel URL immediately communicates what DriftGuard protects.
2. A reviewer can understand approved-baseline drift and low-and-slow accumulation without reading documentation first.
3. The deterministic demo can be stepped through interactively.
4. Custom tool JSON can be analyzed using the real Python DriftGuard engine.
5. The page remains visually calm and uncluttered.
6. The implementation passes Python, web, build, and browser verification.
7. The final application is deployed to Vercel with a shareable URL.
