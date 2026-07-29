---
type: Wiki Overview
title: 'Brainstorm Input: A2UI Integration into `parrot.outputs`'
id: doc:sdd-proposals-a2ui-outputs-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: ai-parrot currently produces rich outputs (folium maps, infographics, reports,
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.interfaces
  rel: mentions
- concept: mod:parrot.outputs
  rel: mentions
---

---
feature: FEAT-XXX  # assign on intake (FEAT-A: rendering core)
follow_up: FEAT-XXX+1  # FEAT-B: ActionRouter + interactive data-flow (D10, gated by SPK-2)
title: "A2UI Protocol Integration — parrot.outputs Rewrite (Rendering Core)"
status: brainstorm-input
date: 2026-07-09
target_branch: dev
template_reference: WhatIfToolkit  # SDD structure template
spec_pipeline: /sdd-brainstorm -> /sdd-proposal -> /sdd-spec -> /sdd-task
---

# Brainstorm Input: A2UI Integration into `parrot.outputs`

## 1. Context & Motivation

ai-parrot currently produces rich outputs (folium maps, infographics, reports,
charts) by generating **arbitrary code/HTML** that is executed or injected
downstream. This is a known security liability (same class as the
`python_repl` incident) and an ad-hoc, non-standard contract per output type.

[A2UI v1.0](https://a2ui.org/specification/v1.0-a2ui/) formalizes exactly the
pattern ai-parrot pioneered internally: **LLM/tool emits a declarative JSON
envelope → validator checks it against a component catalog → deterministic
renderer materializes it**. This is the platform invariant *"probabilistic
components propose; deterministic components decide"* expressed as a wire
protocol, and the catalog is an **allowlist** (WS1 anti-arbitrariness
principle applied to UI).

Strategic bet: adopt A2UI as the wire format of a rewritten `parrot.outputs`,
gaining ecosystem interop (third-party renderers such as **Lynx**) while
exceeding the reference proposal with capabilities A2UI does not contemplate:
**server-side rendering** (HTML → PDF / email / static delivery through
`Agent.notification()`) and **semantic high-level components** (infographics,
reports, custom artifacts) as first-class catalog citizens.

## 2. Decisions (locked)

| ID | Decision | Rationale |
|----|----------|-----------|
| D1 | **Dual envelope producers.** Tools emit A2UI envelopes deterministically from their own data (zero LLM tokens, zero hallucination). The LLM produces envelopes only for freeform UI, via structured output with the prompt→generate→validate loop. | Tool outputs (e.g. route maps) have all data already; involving the LLM is pure risk. Preserves the original Parrot Outputs philosophy. |
| D2 | **Custom catalog *extends* the A2UI Basic Catalog** (own `catalogId`, e.g. `https://parrot.dev/catalogs/v1`). Basic Catalog components remain valid; Parrot adds semantic components. | Keeps compatibility with third-party renderers (Lynx et al.) that Parrot wants to *consume*, per A2UI's swappable-catalog design. |
| D3 | **Target A2UI v1.0 directly** (candidate), not v0.9.1. | No implementer exists yet (not even Google ADK); no legacy to interoperate with. v1.0 brings `actionResponse`/`callFunction` and inline-components `createSurface` (better for SSR one-shot). Version isolated in a single serialization layer (AgentCard dual-emit lesson) so a future spec fork is absorbable. |
| D4 | **Core lives in `parrot.outputs`** (direct replacement of current arbitrary-code outputs). Contract in `parrot.interfaces.outputs` (envelope Pydantic models, `AbstractRenderer`, `RendererCapabilities`, lowering contract). Heavy renderer deps behind lazy imports; granular extras (`ai-parrot[a2ui]`, possibly `[a2ui-pdf]`). | Mirrors `interfaces.file`/`interfaces.o365` seam pattern and the FAISS `_try_create_faiss_store` lazy-import pattern. One-way import rule: `parrot.outputs` core never imports agents, DatasetManager, or LLM clients. |
| D5 | **`ActionRouter` is a new seam**, integrated into the Handlers layer, **AgentTalk first**, then Teams (Bot Framework invoke), WebSocket, A2A. It is an *interceptor* (can affect execution), not a lifecycle subscriber — respects the observability/interception separation (FEAT-176 constraint). **Implementation deferred to follow-up spec (see D10); v1 reserves the contract.** | The action return channel is transport-specific; a unified dispatch seam prevents per-channel divergence. Estimated to be the majority of real implementation effort — which is exactly why it is its own spec. |
| D6 | **Static artifact delivery via `Agent.notification()`** (Teams, Slack, Telegram, email). Flowtask node is **out of scope for v1** (revisit later; `RenderedArtifact` is designed so a Flowtask consumer needs no changes). | Reuses an existing, working delivery surface instead of inventing one. |
| D7 | **Two-tier rendering with a lowering pass.** Each custom catalog component may be consumed natively (full fidelity) by Parrot renderers, or *lowered* — deterministically compiled to a Basic Catalog tree — for third-party renderers and fallback transcoding (e.g. Adaptive Cards without a native mapping). | Ecosystem compatibility becomes a property of the **catalog**, not of every renderer. Lowering is a pure single-pass transform, testable with golden files. |
| D8 | **Lowering is MANDATORY for every custom component** (Infographic, Report, Map, Chart, DataTable, KPICard, ...). A custom component without a lowering implementation does not ship. | Guarantees every Parrot envelope is renderable by any spec-compliant Basic Catalog renderer. No "native-only" islands. |
| D9 | **Action degradation on dead surfaces (PDF/email/static HTML) = deep-link back to the chat.** Interactive actions render as links that resume the conversation/session. | Keeps static artifacts actionable without pretending they have a live data-flow channel. Note: deep-links do NOT require `ActionRouter` — the resumed "action" arrives as a normal user message over the existing channel. |
| D10 | **Two-spec split by surface nature: display vs interactive.** FEAT-A (this spec) = rendering core: envelopes, catalog + lowering, renderer registry, `RenderedArtifact` → `notification()`, deep-link degradation everywhere. FEAT-B (follow-up spec) = live data-flow: `ActionRouter` + transport bindings + interactive components (forms, `callFunction`/`actionResponse` dispatch), gated by SPK-2. Three anti-debt guarantees in FEAT-A: (a) envelope models ship the **complete v1.0 message set** from day one — schemas are cheap, dispatch is not; (b) every catalog component declares `requires_actions`; v1 renderers degrade (deep-link) or reject such components, and the LLM producer path (D1) is constrained to display layouts in v1; (c) CR-4 (AgentTalk seam identification) stays in FEAT-A research so FEAT-B starts with verified anchors. | The security win (killing arbitrary-code outputs) is 100% delivered by the rendering core alone. Splitting isolates the highest-effort, highest-unknown seam behind its own spike gate — spike before spec. |

## 3. Architecture Sketch

```
                      ┌────────────────────────────┐
  Tools (determin.)──►│  A2UI Envelope (Pydantic)  │◄── LLM structured output
                      │  parrot.interfaces.outputs │     (validate loop)
                      └─────────────┬──────────────┘
                                    │  JSONL stream (ask_stream contract unchanged)
                     ┌──────────────┼───────────────────────────┐
                     ▼              ▼                           ▼
              Native renderers   Lowering pass            Transports
              (registry, lazy)   (custom → Basic tree)    SSE/WS (AgentTalk)
              folium │ echarts/  → third-party renderers  A2A (official ext.)
              shadcn │ adaptive    (Lynx, ...)            MCP │ Teams binding
              cards  │ ssr-html  → AC fallback transcode
                     │
                     ▼
              RenderedArtifact ──► Agent.notification() ──► Teams/Slack/Telegram/email
              (static surfaces)          │
                                         └─ actions degraded to chat deep-links (D9)
```

Key elements:

- **Envelope models** (`parrot.interfaces.outputs`): Pydantic v2 models for
  `createSurface`, `updateComponents`, `updateDataModel`, `action`,
  `actionResponse`, `callFunction` (v1.0 message set). Single serialization
  layer owns the `version` field.
- **Catalog** (`parrot.outputs.catalog`): declarative component definitions
  (schema + embedded LLM `instructions` per A2UI spec + mandatory
  `lower(component, data_model) -> BasicTree` per D8). Registered via
  decorator — fractal registry pattern, e.g. `@register_component("Infographic")`.
- **Renderer registry** (`parrot.outputs.renderers`):
  `@register_renderer("adaptive_cards")` etc. Each renderer declares
  `RendererCapabilities` (`interactive: bool`, `supports_actions`,
  `supports_updates`, `output: mime | live`). Static renderers **bake** the
  data model (resolve all JSON Pointers at render time — structurally the
  two-phase prompt rendering pattern: CONFIGURE-bake vs REQUEST-live).
- **`RenderedArtifact`**: the contract between static renderers and
  `Agent.notification()`. ⚠️ VERIFY — a model for this reportedly **already
  exists** in the codebase (see Code Research CR-2); reuse/extend rather than
  invent.
- **`ActionRouter`** (new seam, D5): normalizes transport-specific action
  callbacks (Bot Framework `Action.Submit`/`Action.Execute` invoke, WS
  message, A2A message, deep-link resume) into A2UI `action` messages routed
  to the owning agent/session.

## 4. Code Research Directives (for `/sdd-brainstorm`)

The brainstorm MUST ground the following in source before the proposal.
All contracts use **grep anchors, never line numbers**.

- **CR-1 — Inventory of current `parrot.outputs`.** Enumerate every existing
  output type, which ones generate/execute arbitrary code or HTML, and which
  have external consumers (grep anchor: `_generate_interactive_html_map` in
  `parrot_tools/google/tools.py` is one confirmed arbitrary-HTML producer;
  find all siblings, including the infographic/report composites). Produce
  the replace/keep/deprecate table.
- **CR-2 — `RenderedArtifact` (or equivalent) existing model.** Per user
  confirmation this model is already available in the codebase. Locate it
  (⚠️ VERIFY exact name/module), document its schema, and assess fit for the
  static-renderer → notification contract. Do NOT redesign if reusable.
- **CR-3 — `Agent.notification()` signature and providers.** Confirm
  supported channels (Teams, Slack, Telegram, email), attachment semantics,
  and how a `RenderedArtifact` maps onto them (grep anchors:
  `send_notification`, `SendNotifyReportCallback`,
  `SendEmailReportCallback` in `parrot/scheduler/functions/__init__.py`).
- **CR-4 — AgentTalk handler seams.** Identify where `ActionRouter`
  integrates: request handlers, WS message dispatch, and the existing
  interceptor vs lifecycle-subscriber boundary (FEAT-176 constraint).
- **CR-5 — Structured output pipeline.** Confirm how `AbstractClient`
  structured outputs are declared/validated today, to wire the LLM-producer
  path (D1) with generated envelope models and a validate-retry loop.
- **CR-6 — Lazy import / extras precedents.** Confirm the exact patterns to
  mirror: FAISS `_try_create_faiss_store` fallback and
  `file/__init__.py __getattr__` re-exports, plus current `pyproject` extras
  layout for the new `[a2ui]` extra.
- **CR-7 — Session/deep-link contract (D9).** What does a chat resume URL
  look like today per channel? Does a session-resurrection mechanism exist,
  and can an action payload survive the round-trip (signed token vs opaque
  ref)? ⚠️ VERIFY — likely partially does NOT exist.

## 5. Does NOT Exist (assumed — brainstorm must confirm)

- No A2UI envelope models, catalog module, or renderer registry anywhere in
  the monorepo.
- No `ActionRouter` or unified cross-transport action dispatch.
- No lowering/compilation infrastructure for composite outputs.
- No deep-link action-resume contract for static artifacts (CR-7).
- No Adaptive Cards transcoder driven by a declarative envelope (current
  Teams cards, if any, are ad-hoc — ⚠️ VERIFY).

## 6. Spike Gates (must precede `/sdd-spec`)

- **SPK-1 — Rasterization backend for infographics/reports (OQ9, confirmed).**
  `playwright` headless (full JS fidelity for ECharts, heavy, timing
  nondeterminism in containers) vs `weasyprint` (deterministic, no JS —
  requires charts pre-rendered to static SVG). Decide per-artifact-class if
  needed. Exit criterion: one real infographic envelope → PDF + email-safe
  HTML through both paths, measured for size, latency, determinism.
- **SPK-2 — Teams action round-trip (moved: gate for FEAT-B, not this spec).**
  A2UI `action` → `Action.Submit`/`Execute` → Bot Framework invoke → back to
  A2UI `action` message through `ActionRouter`. De-risks the largest unknown
  of D5/D10. Must pass before the FEAT-B `/sdd-spec`.
- **SPK-3 — LLM envelope fidelity (light).** Measure structured-output
  validity rate for the custom catalog with embedded `instructions` on
  Claude + Gemini; calibrates how much the validate-retry loop must carry.

## 7. Remaining Open Questions

- **OQ-A** Deep-link mechanics (depends on CR-7): URL scheme per channel,
  payload transport (signed token?), session resurrection semantics.
- **OQ-B** Catalog v1 component list: `Infographic`, `Report`, `Map`,
  `Chart`, `DataTable`, `KPICard` — confirm against CR-1 inventory; anything
  currently shipped that this set does not cover?
- **OQ-C** Lowered-tree fidelity contract for Infographic/Report: minimum
  acceptable degradation (golden-file review criteria).
- **OQ-D** Streaming granularity: emit `updateComponents` incrementally
  during generation (A2UI's streaming selling point) or envelope-complete
  per output? Interacts with `ask_stream` chunking.

## 8. v1 Scope / Non-Goals

**In (FEAT-A, this spec):** envelope models + validation (complete v1.0
message set, D10a), custom catalog with mandatory lowering (D8) and
`requires_actions` declaration (D10b), renderer registry with capabilities,
native renderers (SSR HTML, folium-map, ECharts/shadCN payload, Adaptive
Cards — display subset), static baking + `RenderedArtifact` →
`notification()`, deep-link degradation (D9), A2UI-A2A extension emit
(display), CR-4 seam research.

**Out (deferred to FEAT-B follow-up spec, gated by SPK-2):** `ActionRouter`
implementation and all transport action bindings, interactive components
(forms/submit), `callFunction`/`actionResponse` dispatch, LLM-generated
interactive UI.

**Out (no spec planned yet):** Flowtask node (D6), voice/LiveAvatar surface,
catalog authoring UI, v0.9.1 compatibility emit (revisit only if the
ecosystem forks).
