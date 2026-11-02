# Desktop design system

The prototype uses a calm local workspace with restrained violet accents. It does
not copy Apple branding, assets or product screens. System fonts follow macOS,
Windows and Linux conventions; the native window retains platform decorations.

| Foundation | Implementation |
|---|---|
| Typography | `-apple-system`, BlinkMacSystemFont, Segoe UI Variable/Segoe UI, system sans; SF Mono/Consolas for exact evidence |
| Surfaces | Light: near-white workspace, white content, pale navigation. Dark: neutral near-black workspace and restrained elevated surfaces |
| Accent | Violet for navigation, focus, selection and primary review controls |
| Status | Text plus semantic green/amber/red; color is never the sole status cue |
| Hierarchy | One page heading, small descriptive text, aligned review panels and compact evidence sections |
| Spacing | Consistent panel padding/gaps, shallow borders and minimal shadows |
| Icons | Inline code-defined SVG; no remote icon/image/font requests |
| Motion | Small state transitions; all transitions/animations disabled with reduced-motion preference |
| Focus | Visible keyboard focus, skip-to-content link, native modal focus containment and restoration |

The flagship review uses parallel approved/observed definitions with field-change
highlights, a plain-language evidence list, exact-hash metadata and explicit approve,
deny and quarantine actions. Approval opens a version-specific confirmation.
Quarantined versions cannot be approved. Tool names remain unbroken in the selector;
long names truncate visually and remain available through accessible text/title.

Timeline charts show recorded values and leave gaps for missing metrics. An absent
score is never drawn as zero. A selected version exposes exact values and its
definition. Approved-reference markers refer to recorded consent baselines.

Empty states describe the next useful action. Browser preview and guided fixture
mode visibly disclaim live protection. Imported sources are review-only. Settings
state the current absence of cloud providers, credential storage and authenticated
remote setup. The app does not invent risk percentages, connected-client counts,
protection success rates or publication results.

The native window minimum is 900×680. At 900px the review comparison stacks and
secondary layouts become single-column. Light/dark themes, reduced motion, keyboard
navigation and screen-reader labels are implemented. Browser screenshots and
automated sampled accessibility checks are recorded in
[CROSS_PLATFORM_TESTING.md](CROSS_PLATFORM_TESTING.md); native and assistive-technology
verification must be performed on actual target platforms before release.
