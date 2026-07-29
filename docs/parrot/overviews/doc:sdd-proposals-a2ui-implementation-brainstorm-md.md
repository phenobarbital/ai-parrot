---
type: Wiki Overview
title: 'Brainstorm: A2UI Protocol Integration — `parrot.outputs` Rendering Core (FEAT-A)'
id: doc:sdd-proposals-a2ui-implementation-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: ai-parrot's rich-output pipeline produces maps, charts, infographics, tables
  and
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.auth
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.registry
  rel: mentions
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.interfaces
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.notifications
  rel: mentions
- concept: mod:parrot.outputs
  rel: mentions
- concept: mod:parrot.outputs.a2ui
  rel: mentions
- concept: mod:parrot.outputs.a2ui.catalog
  rel: mentions
- concept: mod:parrot.outputs.a2ui.models
  rel: mentions
- concept: mod:parrot.outputs.a2ui.renderers
  rel: mentions
- concept: mod:parrot.outputs.formats
  rel: mentions
- concept: mod:parrot.storage.models
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: A2UI Protocol Integration — `parrot.outputs` Rendering Core (FEAT-A)

**Date**: 2026-07-10
**Author**: Jesus Lara (discovery) + Claude (research/synthesis)
**Status**: exploration
**Recommended Option**: A
**Input document**: `sdd/proposals/a2ui-outputs-brainstorm.md` (locked decisions D1–D10 carried forward)
**Follow-up feature**: FEAT-B — ActionRouter + interactive data-flow (gated by SPK-2, out of scope here)

---

## Problem Statement

ai-parrot's rich-output pipeline produces maps, charts, infographics, tables and
reports by having the LLM emit **arbitrary Python code or raw HTML** that the
framework then executes or injects downstream. Code research (CR-1) confirmed
the scale of the liability:

- Six chart renderers (`altair`, `plotly`, `matplotlib`, `seaborn`, `echarts`,
  `map`) run LLM-generated Python through a raw `exec()` in
  `BaseRenderer.execute_code` — the same class of vulnerability as the
  `python_repl` incident.
- At least seven renderers/templates emit full raw HTML documents injected
  downstream (`html` pass-through, `table`, `card`, `infographic_html`,
  `jinja2`, `template_report`, `chart` base), plus a Panel generator with its
  own `exec()`.
- Three tool-level producers build raw HTML outside `parrot.outputs` entirely
  (`InteractiveToolkit` vibe-coding canvas, `InfographicToolkit`, the Google
  routes `_generate_interactive_html_map`).

Every output type is an ad-hoc, non-standard contract. [A2UI
v1.0](https://a2ui.org/specification/v1.0-a2ui/) formalizes the pattern the
`STRUCTURED_CHART/TABLE/MAP` renderers already pioneered internally:
**producer emits a declarative JSON envelope → validator checks it against a
component catalog (allowlist) → deterministic renderer materializes it**.
Adopting it as the wire format of a rewritten `parrot.outputs` kills the
arbitrary-code channel, standardizes the contract, and buys ecosystem interop
(third-party renderers such as Lynx) — while Parrot exceeds the spec with
server-side rendering (HTML → PDF/email via notifications) and semantic
high-level components (Infographic, Report, …) as first-class catalog
citizens.

**Who is affected**: agent/tool developers (new deterministic envelope API),
end users on every surface (chat HTML, Teams, Slack, Telegram, email, PDF),
and security posture (removal of `exec()` sinks once migration completes).

## Constraints & Requirements

Locked decisions D1–D10 from the input document all remain in force, with the
discovery refinements below. Hard constraints:

- **Security invariant**: the new pipeline must contain zero `exec()`/raw-HTML
  injection paths. Catalog = allowlist; envelopes are data, never code.
- **D1 dual producers**: tools emit envelopes deterministically from their own
  data (zero LLM involvement); the LLM produces envelopes only for freeform UI
  via structured output + a validate-retry loop (which does **not** exist at
  the client level today and must be built — CR-5).
- **D3 target A2UI v1.0** directly; `version` owned by a single serialization
  layer. Ship the **complete v1.0 message set** (`createSurface`,
  `updateComponents`, `updateDataModel`, `action`, `actionResponse`,
  `callFunction`) as models from day one (D10a), even though FEAT-A only
  dispatches display messages.
- **Packaging (discovery, supersedes D4's location detail)**: envelope models,
  catalog, component/renderer registries, and lowering live in **ai-parrot
  core under `parrot.outputs`** (NOT `parrot.interfaces.outputs`); ALL
  concrete renderers live in **`ai-parrot-visualizations`** via the
  established PEP 420 namespace merge. One-way import rule: core
  `parrot.outputs` never imports agents, DatasetManager, or LLM clients.
- **D7/D8 mandatory lowering**: every custom catalog component ships a pure,
  deterministic `lower()` to a Basic Catalog tree, golden-file tested. No
  native-only islands.
- **D10b**: every catalog component declares `requires_actions`; FEAT-A
  renderers degrade (deep-link) or reject such components; the LLM producer
  path is constrained to display layouts in v1.
- **Streaming (discovery, resolves OQ-D)**: envelope-complete per output in
  v1 — one complete surface streamed as a single JSONL item over the existing
  `ask_stream` chunked contract. Incremental `updateComponents` deferred to
  FEAT-B.
- **Migration (discovery)**: coexist + deprecate. Legacy `OutputMode` formats
  keep working, marked deprecated; per-format cutover tracked in the
  replace/keep/deprecate table below. Removal is a later feature.
- **Deep links (discovery, expands D9)**: signed-token action resume is IN
  FEAT-A scope. Resume = token verified → action injected as a **structured
  user message** into the conversation (no ActionRouter needed). Resume routes
  are **per-channel integration** responsibilities, not a unified endpoint.
- **Spike gates**: SPK-1 (rasterization backend) and SPK-3 (LLM envelope
  fidelity) must run after this brainstorm's review and **before
  `/sdd-spec`**. SPK-2 (Teams round-trip) gates FEAT-B only.

---

## Options Explored

### Option A: A2UI-native rendering core in `parrot.outputs.a2ui`, renderers in the visualizations satellite

Build a new subsystem `parrot.outputs.a2ui` (core package) implementing the
A2UI v1.0 envelope models, a Parrot custom catalog
(`https://parrot.dev/catalogs/v1`) extending the Basic Catalog, a component
registry and a renderer registry (both decorator-based, mirroring
`register_renderer`/`supported_stores` precedents), and the mandatory lowering
pass. All concrete renderers (SSR-HTML, folium map, ECharts payload, Adaptive
Cards display subset, PDF rasterization) ship from
`ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/` gated behind new
extras (`a2ui`, `a2ui-pdf`). Static renderers bake the data model (resolve all
JSON Pointers at render time) into a new `RenderedArtifact` model delivered
through the existing `NotificationMixin.send_notification()` surface. Signed
deep-link tokens (Redis-backed one-shot, following the OAuth2 nonce
precedent) let static surfaces resume the conversation per channel. Legacy
formats coexist, marked deprecated.

✅ **Pros:**
- Delivers the full security win: a complete declarative replacement for every
  `exec()`/raw-HTML path, with the allowlist enforced by catalog validation.
- Wire-format interop with the A2UI ecosystem (Lynx et al.) via mandatory
  lowering — compatibility is a property of the catalog, not each renderer.
- Follows three battle-tested in-repo seams exactly: satellite namespace merge
  (FEAT-200/201), registry-dict + `importlib` dispatch, decorator
  registration.
- Coexistence de-risks migration; the CR-1 table gives a per-format cutover
  plan; `STRUCTURED_*` renderers are near-drop-in lowering targets.
- FEAT-B (ActionRouter) starts with verified seam anchors (CR-4 complete:
  AgentTalk chunked HTTP, `handlers/stream.py` WS loop, Teams
  `activity.value` card-submit path, frozen-event lifecycle registry).

❌ **Cons:**
- Highest effort of the three options: envelope models + catalog (9+
  components × schema + lowering + golden files) + registries + 4-5 renderers
  + `RenderedArtifact` + deep-link tokens + LLM producer loop.
- Dual maintenance while legacy formats live (deprecation period unbounded).
- A2UI v1.0 is a candidate spec with no other implementer yet — spec-fork risk
  absorbed by the single serialization layer, but real.
- Teams/Slack cannot receive real file attachments today (CR-3), so PDF
  delivery there needs the public-URL fallback (`ArtifactStore.get_public_url`)
  until Graph-upload work lands.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic==2.12.5` | Envelope + catalog models | already core dependency |
| `jsonpointer>=2.4` | A2UI data-model binding resolution (bake pass) | tiny, pure-python; new core dep or vendored resolver |
| `jsonschema` | Catalog component schema validation | already used in `flows/flow/actions.py` |
| `weasyprint` | HTML → PDF (SPK-1 candidate, deterministic, no JS) | already in `pdf` extra |
| `playwright` | HTML → PDF/PNG (SPK-1 candidate, full JS fidelity) | already in `agents` extra |
| `folium` | Map renderer | already in visualizations `map` extra |
| vendored `echarts.min.js` | ECharts SSR/HTML renderer | already in visualizations assets |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/outputs/formats/__init__.py` — decorator
  registry + lazy `_MODULE_MAP` dispatch pattern (anchor
  `def register_renderer`).
- `packages/ai-parrot/src/parrot/embeddings/registry.py` — core→satellite
  `importlib` dispatch seam (anchor `module_path = f"parrot.embeddings.{model_type}"`).
- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_*.py`
  — declarative config renderers; schemas inform Chart/DataTable/Map catalog
  components and their lowerings.
- `packages/ai-parrot/src/parrot/notifications/__init__.py` —
  `NotificationMixin.send_notification` delivery surface (anchor
  `async def send_notification`).
- `packages/ai-parrot/src/parrot/storage/artifacts.py` — `ArtifactStore`
  (`get_public_url`) for public-HTML fallback delivery.
- `packages/ai-parrot/src/parrot/auth/oauth2_base.py` — Redis one-shot nonce
  pattern (anchor `_NONCE_KEY_TEMPLATE`) for signed deep-link tokens.
- `packages/ai-parrot/src/parrot/outputs/formatter.py` —
  `format_with_retry`/`DEFAULT_RETRY_PROMPTS` as the precedent for the LLM
  envelope validate-retry loop.
- `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py`
  — suspended-session resume seam (anchor `get_suspended_session`) as the
  template for per-channel deep-link resume.

---

### Option B: Evolve the `STRUCTURED_*` family into a proprietary Parrot declarative format (no A2UI)

Skip the A2UI wire format. Generalize the existing
`StructuredChartConfig`/`StructuredTableConfig`/`StructuredMapConfig` models
into a full Parrot-proprietary declarative envelope covering all output types
(infographic, report, card, …), extend the existing
`register_renderer`/`OutputMode` machinery with deterministic renderers, and
deprecate the code-executing paths the same way.

✅ **Pros:**
- Lowest conceptual distance: extends models and registries that already ship
  and already have three working renderers and system prompts.
- No external-spec risk (A2UI v1.0 is still a candidate with no other
  implementer).
- Roughly 30–40% less work: no lowering pass, no catalog/`catalogId`
  machinery, no A2UI message-set models.

❌ **Cons:**
- Zero ecosystem interop — no third-party renderer can ever consume Parrot
  outputs; every new surface is Parrot's to build forever.
- Re-invents what A2UI already specifies (component catalog, data-model
  binding, versioning) with a proprietary dialect that will drift.
- Abandons the strategic bet of the input document (D2/D3 explicitly locked
  A2UI compatibility); a later migration to A2UI would be a second rewrite.
- The `OutputMode` enum + `(content, wrapped)` tuple contract is itself part
  of the legacy debt (debug file-writes, double registrations, dead modes —
  CR-1); building on it entrenches it.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic==2.12.5` | Envelope models | already core |
| `weasyprint` / `playwright` | rasterization | same SPK-1 question applies |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_base.py`
  — `StructuredOutputBase` (`_extract_rows`, `_route_envelope`) as the base.
- `packages/ai-parrot/src/parrot/models/outputs.py` — `StructuredChartConfig`
  et al. grow into the envelope vocabulary.
- Same notification/artifact reuse as Option A.

---

### Option C (unconventional): Basic-Catalog-only adapter — author directly to the A2UI Basic Catalog, no custom components

Adopt A2UI but skip the custom catalog entirely. Tools and the LLM emit Basic
Catalog trees directly (Text, Image, Row, Column, Card, Button, …); a thin
`parrot.outputs.a2ui` adapter validates and hands them to third-party
renderers (Lynx web renderer) or a single minimal SSR-HTML renderer.
Infographics/reports become authoring conventions (compositions of basic
components) rather than semantic components.

✅ **Pros:**
- Smallest possible surface: no catalog authoring, no lowering pass (there is
  nothing to lower), no per-component golden files.
- Maximum ecosystem compatibility by construction — everything is Basic
  Catalog from birth.
- Fastest route to killing `exec()` for simple outputs.

❌ **Cons:**
- Loses semantic components entirely: an "Infographic" becomes an unnamed div
  soup — no high-fidelity native rendering, no server-side semantic knowledge
  (e.g., "render this Report as paginated PDF" has no component to hang logic
  on). Directly contradicts locked D2/D7/D8 and the strategic bet.
- Complex outputs (maps, ECharts) don't exist in the Basic Catalog at all —
  they would need escape hatches that reintroduce the arbitrary-payload
  problem.
- LLM authoring burden explodes: composing a good infographic from primitives
  every time vs. filling a semantic component's schema (SPK-3 risk way up).

📊 **Effort:** Low (but does not meet requirements)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic==2.12.5` | Basic Catalog models | already core |
| Lynx (JS, client-side) | third-party web renderer | consumer-side, not a Python dep |

🔗 **Existing Code to Reuse:**
- Minimal: `handlers/agent.py` `_format_response` seam to emit the envelope.

---

## Recommendation

**Option A** is recommended because:

- It is the only option that satisfies the locked decision set (D2 custom
  catalog, D3 A2UI v1.0, D7/D8 lowering) *and* the security requirement in
  full. Option B trades the ecosystem bet for ~30% less effort — a bad trade
  given the input doc explicitly locked A2UI interop as strategic. Option C
  fails the semantic-component requirement outright and would push complex
  outputs back toward arbitrary payloads.
- Its real risk — A2UI v1.0 being a candidate spec — is contained by design:
  the single serialization layer owns `version`, and mandatory lowering means
  even a spec fork leaves Parrot's native renderers untouched.
- Its effort is front-loaded in exactly the places research de-risked:
  registries and satellite packaging follow verbatim in-repo precedents, and
  the `STRUCTURED_*` schemas give Chart/DataTable/Map lowering a head start.
- What we accept: dual maintenance during the coexistence window, and the
  Teams/Slack attachment gap being papered over with public-URL links until a
  Graph-upload capability exists (tracked as an open question).

---

## Feature Description

### User-Facing Behavior

- **Chat (AgentTalk/web)**: an agent/tool response that today returns wrapped
  HTML instead carries an A2UI envelope in the `AIMessage`; the web client (or
  an embedded Lynx renderer) renders it. Existing `output_format=html`
  consumers keep working via the SSR-HTML renderer, which materializes the
  same envelope server-side.
- **Static surfaces (email, PDF, Teams/Slack/Telegram notifications)**: a
  scheduled report or an explicit "send me this as PDF" produces a
  `RenderedArtifact` (baked HTML or PDF) delivered through
  `send_notification()`. Email/Telegram get real attachments; Teams/Slack get
  the message plus a public artifact URL.
- **Actions on static surfaces**: any component that declares
  `requires_actions` renders on a dead surface as a **deep link** — a signed,
  single-use URL that reopens the originating channel/session; clicking it
  resumes the conversation with the action injected as a structured user
  message ("User clicked *Approve* on report X"). Live interactive dispatch
  (forms, `callFunction`) arrives in FEAT-B.
- **Developers**: tools construct envelopes with typed builders
  (deterministic, D1); agents can request LLM-generated display layouts which
  are validated against the catalog and retried on failure before anything
  reaches a renderer.

### Internal Behavior

1. **Envelope layer** (`parrot.outputs.a2ui.models`, core): Pydantic v2
   models for the complete v1.0 message set; one serialization module owns
   the `version` field and JSONL emit. Validation rejects unknown components
   (allowlist) and unresolvable JSON Pointer bindings.
2. **Catalog** (`parrot.outputs.a2ui.catalog`, core): `@register_component`
   decorator registers each component's schema, embedded LLM `instructions`,
   `requires_actions` flag, and mandatory `lower(component, data_model) →
   BasicTree` implementation. v1 components: `Infographic`, `Report`, `Map`,
   `Chart`, `DataTable`, `KPICard`, `Card`, `Timeline`, plus `Form`
   (schema-only, `requires_actions=True`, rejected/deep-linked by v1
   renderers). The CR-1 inventory confirms this set covers everything the
   legacy formats ship (markdown/text/JSON wrap map to Basic Catalog
   primitives; `APPLICATION`/Streamlit/Panel is out of scope, see
   deprecation table).
3. **Renderer registry** (`parrot.outputs.a2ui.renderers`, core registry;
   concrete classes in `ai-parrot-visualizations`): `@register_renderer_a2ui`
   + a name→class dict resolved via `importlib` over the namespace (the
   `supported_stores` pattern). Each renderer declares
   `RendererCapabilities(interactive, supports_actions, supports_updates,
   output=mime|live)`. v1 renderers: `ssr-html`, `folium-map`,
   `echarts-payload`, `adaptive-cards` (display subset), `pdf`
   (SPK-1-decided backend). Non-native renderers receive the lowered Basic
   tree.
4. **Baking**: static renderers resolve every data-model JSON Pointer at
   render time (two-phase CONFIGURE-bake vs REQUEST-live split), producing a
   self-contained document with zero live bindings.
5. **`RenderedArtifact`** (new model — CR-2 confirmed nothing reusable
   exists): `{artifact_id, mime_type, content|path, filename, title,
   source_envelope_ref, surface, deep_links[], metadata}`. Bridges renderers
   → `send_notification(report=…)` (whose attachment extraction reads
   `report.files`) and → `ArtifactStore` for public-URL delivery.
6. **Deep-link tokens**: minted at bake time per degraded action —
   single-use, TTL-bound, stored server-side keyed by
   `a2ui:resume:{token}` (Redis, mirroring `_NONCE_KEY_TEMPLATE`), carrying
   `{session_id, user_id, agent_id, channel, action_payload}`. Each
   integration ships its own tiny resume route that verifies+consumes the
   token and injects the action as a structured user message through its
   existing inbound seam (Telegram's suspended-session flow is the template;
   Teams via `activity.value`-style message; web via AgentTalk POST).
7. **Producers**: (a) tools build envelopes via typed builders — a new
   `A2UIToolkit`-style surface plus migration of `InfographicToolkit`/
   `InteractiveToolkit` semantics; (b) LLM path wires
   `structured_output=<envelope model>` through the existing
   `StructuredOutputConfig` machinery and adds the **envelope validate-retry
   loop** (catalog validation errors → re-prompt with error context, bounded
   attempts — the `format_with_retry`/`DEFAULT_RETRY_PROMPTS` pattern lifted
   to envelope level, since no client-level retry exists).
8. **Emission**: `AIMessage` gains an envelope carrier (new field or
   `artifacts[]` entry — spec decision); `OutputMode.A2UI` added for the
   transition so `_resolve_output_mode`/handlers can route to the new
   pipeline without breaking the legacy enum contract; A2UI-A2A extension
   emit wraps the envelope in the existing `a2a` `Artifact.parts`.

### Replace / keep / deprecate (CR-1 inventory → cutover plan)

| Legacy format(s) | Risk | Fate |
|---|---|---|
| `altair`, `plotly`, `matplotlib`, `seaborn`, `echarts`, `map` | exec + raw HTML | **Replace** → `Chart` / `Map` components |
| `html` (pass-through), `table`, `card`, `infographic_html` | raw HTML | **Replace** → SSR-HTML renderer / `DataTable` / `Card` / `Infographic` |
| `structured_chart/table/map` | config-only | **Replace** (schemas absorbed into catalog; nearest precursors) |
| `jinja2`, `template_report` | template HTML | **Replace** → `Report` component (templates become lowerings) |
| `infographic` (JSON), `json`, `yaml`, `markdown` | none | **Keep** (plain data/formatting, not UI) |
| `slack`, `whatsapp` | none | **Keep** (text-formatting transports; later become lowering targets) |
| `application` (Streamlit/Panel + `exec`) | exec | **Deprecate** (no A2UI equivalent; kill the Panel `exec` path) |
| `InteractiveToolkit`, `InfographicToolkit`, google `_generate_interactive_html_map` | raw HTML tools | **Replace** → deterministic envelope builders (D1) |

### Edge Cases & Error Handling

- **Invalid envelope from LLM**: catalog validation fails → bounded
  re-prompt loop (SPK-3 calibrates attempts); final failure degrades to a
  plain-text answer, never to raw passthrough.
- **Envelope references unknown component**: hard reject (allowlist) with a
  structured error naming the component and the catalog version.
- **Renderer missing for requested surface**: fall back to lowering + any
  Basic-Catalog-capable renderer; if none, `RenderedArtifact` with SSR-HTML.
- **`requires_actions` component on a static surface**: actions degrade to
  deep links (D9); if deep-linking is impossible (no session context), the
  component renders with actions stripped and a visible notice.
- **Expired/replayed deep-link token**: single-use consume → friendly
  "session expired" landing; token never reveals payload contents.
- **Satellite renderer not installed** (`ImportError` through registry):
  actionable error naming the extra (`pip install ai-parrot-visualizations[a2ui]`),
  mirroring the embeddings registry's `Cannot import embedding module` error.
- **Oversized envelope/data model**: reuse the `ArtifactStore` 200 KB S3
  overflow convention for stored envelopes.
- **Teams/Slack attachment gap**: automatic downgrade to public-URL delivery;
  logged as degraded, never a silent drop.

---

## Capabilities

### New Capabilities
- `a2ui-envelope-models`: complete A2UI v1.0 message-set Pydantic models +
  single-owner serialization/validation layer (core).
- `a2ui-component-catalog`: Parrot custom catalog with `@register_component`,
  embedded LLM instructions, `requires_actions`, and mandatory lowering to
  Basic Catalog trees with golden-file tests (core).
- `a2ui-renderer-registry`: capability-declaring renderer registry with
  core→satellite `importlib` dispatch and extras gating (core + viz).
- `a2ui-native-renderers`: ssr-html, folium-map, echarts-payload,
  adaptive-cards (display subset), pdf renderers (ai-parrot-visualizations).
- `rendered-artifact-delivery`: new `RenderedArtifact` model, baking pass,
  `send_notification()` bridge, `ArtifactStore` public-URL fallback.
- `deep-link-action-resume`: signed single-use resume tokens + per-channel
  resume routes injecting actions as structured user messages.
- `a2ui-llm-producer`: LLM envelope generation via `StructuredOutputConfig` +
  catalog-validate-retry loop (display layouts only in v1).
- `legacy-outputs-deprecation`: deprecation warnings + cutover table wiring
  for the replaced formats (no removals in FEAT-A).

### Modified Capabilities
- Output emission path in `bots/base.py` / `handlers/agent.py`
  (`OutputMode.A2UI` routing alongside the legacy formatter).
- `AIMessage` envelope/artifact carrier fields.
- A2A emit (`a2a/models.py` `Artifact`) wraps A2UI envelopes (display).
- pyproject extras: new `a2ui` (+ `a2ui-pdf`) extras on
  `ai-parrot-visualizations`, referenced from host `charts`/`visualizations`/`all`.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|

…(truncated)…
