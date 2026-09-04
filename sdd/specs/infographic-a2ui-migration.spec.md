---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Infographic → A2UI migration (dual-emit)

**Feature ID**: FEAT-527
**Date**: 2026-09-04
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.29.0
**Source proposal**: `sdd/proposals/infographic-a2ui-migration.proposal.md` (research audit: `sdd/state/FEAT-527/`)

---

## 1. Motivation & Business Requirements

### Problem Statement

AgentTalk infographic turns are **the legacy HTML lane today**. `InfographicToolkit`
renders every infographic through `InfographicHTMLRenderer` (a path FEAT-273 G7 marks
as deprecated) and only attaches an A2UI envelope when constructed with
`emit_a2ui=True` — which **no production caller does** (`InfographicAuthoringMixin`,
`InfographicTalk._get_render_toolkit`, `ResultAgent` all use the default; only the
example walkthrough enables it). Bots therefore set `OutputMode.INFOGRAPHIC`,
`AgentTalk._format_infographic_response` returns an HTML URL / inline document, and the
bundled Svelte UI iframes it.

Meanwhile the **backend A2UI lane is complete but dormant**: an `Infographic` catalog
component (FEAT-470), a pure adapter `infographic_response_to_envelope` (lossy by
design), `build_infographic`, recipes (FEAT-324), bot/handler routing on
`a2ui_envelope`, persisted `ui_surfaces` (FEAT-492) and HTML renderers sharing the
same `DesignSystem` themes (FEAT-493). Three things block using it:

1. **Policy contradiction.** G7 deprecates the HTML lane and every toolkit
   construction trips the `DeprecationWarning`, yet FEAT-493 (2026-09-02) re-invested
   in that lane and its spec treats `formats/infographic_html.py` as a converging
   sibling, not a dead path.
2. **Lossy adaptation.** The adapter collapses 7 chart types and drops every
   presentation field (`layout`, `color_by_sign`, per-series colours, table `style`,
   bullet `columns`, hero-card `icon`/`color`), so a migrated `financial_variance`
   would not look like today's.
3. **No frontend.** The bundled `ai-parrot-server/ui` has zero A2UI rendering (the
   only "a2ui" string is a generated type) and covers 12 of 19 block types; the A2UI
   Svelte renderer is specified for the external navigator-frontend-next.

Terminology the proposal settled (carried forward, not re-opened):
- **Templates are not Jinja/HTML.** `InfographicTemplate` is a Pydantic block-order
  *prompt spec* (`to_prompt_instruction()`); the only Jinja is the trusted
  `render_template` / `render_data_template` lane (FEAT-327).
- **Blocks** are 19 Parrot-specific Pydantic models with no A2UI equivalent.
- **Themes** are already lane-neutral (`ThemeConfig` → `DesignSystem`) and need no
  migration.

### Goals

- **G1 — Dual-emit by default (proposal U1).** Every infographic render (typed blocks,
  Jinja template, data-splice template) produces **both** the HTML artifact and a
  validated A2UI v1.0 envelope; the HTML lane is a permanent sibling emission, not a
  deprecated path. FEAT-273 G7 wording is amended accordingly and the unconditional
  `DeprecationWarning` is removed.
- **G2 — One turn serves both consumers.** An `OutputMode.INFOGRAPHIC` response keeps
  its documented HTML envelope and additionally carries `a2ui_envelope`; an
  `OutputMode.A2UI` response additionally exposes `metadata.html_url` /
  `metadata.artifact_id` so an HTML consumer can still iframe it.
- **G3 — Presentation parity before templates change (proposal U3).** The
  `Infographic`/`Chart`/`DataTable`/`KPICard` catalog surface and the adapter carry the
  chart types and presentation fields the adapter currently drops; `InfographicResponse`
  stays the LLM contract.
- **G4 — Bundled UI renders A2UI infographics (proposal U2).** A minimal Svelte 5 A2UI
  `Infographic` renderer in `packages/ai-parrot-server/ui`, feature-flagged, with the
  iframe HTML view kept as a toggle/fallback. navigator-frontend-next remains the
  primary A2UI consumer and is unaffected.
- **G5 — Jinja lane wrapped as an opaque HTML surface (proposal U4).** `render_template`
  and `render_data_template` emit an A2UI surface whose root is a new display-only
  `HtmlDocument` Parrot component carrying the (trusted, already-rendered) HTML, replacing
  today's synthetic title+summary envelope.
- **G6 — No behaviour change for consumers that ignore `a2ui_envelope`.** Existing HTML
  envelope shape, `html_url` signing, CSP headers, streaming gate and artifact
  persistence are unchanged.

### Non-Goals (explicitly out of scope)

- **Retiring `OutputMode.INFOGRAPHIC` or `InfographicHTMLRenderer`.** Rejected in the
  proposal (U1 = dual-emit permanently).
- **Re-expressing the 10 built-in `InfographicTemplate`s as recipes / `LayoutSpec`s**, or
  deprecating the block models. Deferred until G3 lands (U3).
- **A full generic A2UI renderer in the bundled UI** (inputs, actions, `callAgentFunction`,
  `FilterBar`, `Map`). Only the display-only `Infographic` subtree and the primitives it
  lowers to (§3 Module 3). Action-bearing components degrade to a visible placeholder.
- **Changing navigator-frontend-next** or `docs/frontend/agentdashboard-a2ui-reference.md`
  contracts beyond documenting the new `a2ui_envelope` presence and `HtmlDocument`.
- **Changing `RecipeRunner`, `FlexDashboard`, or the `ui_surfaces` REST lane** — they
  already produce A2UI-native infographics.
- **Rewriting the 12 existing Svelte block components** (`infographic/blocks/*`); they
  remain for the legacy `mode: "json"` tab data.
- **CDN assets or new frontend dependencies** beyond what `package.json` already ships
  (FEAT-493 self-contained invariant holds for backend renderers; the SPA already vendors
  its chart library via the existing chart block).

---

## 2. Architectural Design

### Overview

The migration is a **routing and parity change, not new machinery**:

1. **Toolkit** — `InfographicToolkit.emit_a2ui` defaults to `True`. `render()` keeps
   building the HTML artifact first (unchanged), then always calls
   `_build_a2ui_envelope()`; failure still degrades to HTML-only (additive lane). The
   deprecated-renderer warning in `get_infographic_html_renderer()` is removed; the JSON
   and HTML infographic renderers become the documented "HTML sibling" of the A2UI lane.
2. **Bots** — the post-loop `InfographicRenderResult` branch in `PandasAgent.ask()` and
   `BaseBot` no longer *switches* to A2UI when an envelope is present. New rule:
   - requested `output_mode == OutputMode.A2UI` → `finalize_a2ui_response(response)` **and**
     `response.metadata["html_url"|"artifact_id"|"template_name"|"theme"]` populated from
     the render result;
   - otherwise → `_finalize_infographic_response(response, envelope)` (HTML in `output`,
     `OutputMode.INFOGRAPHIC`) **and** `response.a2ui_envelope = envelope.a2ui_envelope`.
3. **AgentTalk** — `_format_infographic_response` adds `"a2ui_envelope"` to the JSON
   envelope when present (mirrors the FEAT-473 G9 widening already done for the generic
   path at `agent.py:2834-2840`). The `OutputMode.A2UI` early return includes
   `metadata` (with `html_url`) instead of the current four keys. The INFOGRAPHIC
   no-streaming gate stays (signed URL atomicity — resolved: keep).
4. **Catalog parity** — `adapters/infographic.py` forwards the presentation fields the
   `Chart` schema already accepts (`color_by_sign`, `palette`, `positive_color`,
   `negative_color`, `trendline`, `x_axis_mode`) and stops collapsing `donut`/`radar`
   (already in `ChartType`). `ChartType` gains `gauge`, `funnel`, `waterfall`,
   `heatmap`, `treemap`; ECharts renderer implements them natively; Chart.js
   (`interactive-html`) and the bundled UI degrade with a recorded `degraded` entry.
   `Chart` gains `layout: "full"|"half"`, `DataTable` gains `style`, `KPICard` gains
   `icon`, `color`, `comparisonPeriod`; the `Infographic` lowering honours `layout`
   by wrapping half-width siblings in a `Row`. Golden fixtures are regenerated.
5. **Bundled UI** — a new `canvas/a2ui/` component set renders the `Infographic`
   composite from `a2ui_envelope` (JSON-pointer binding resolution against
   `dataModel`), behind `features.a2ui`. `InfographicTabData` gains `mode: "a2ui"` and
   an `envelope` field; `AgentChat.maybeOpenInfographicCanvas` opens the canvas for
   `output_mode ∈ {"infographic","a2ui"}` when an envelope with an `Infographic`/
   `Report` root is present, keeping the iframe path as the toolbar's "HTML" view.
6. **Opaque HTML surface** — new Parrot component `HtmlDocument` (display-only,
   `tool_only=True` so LLM-origin envelopes are rejected at validation). `render_template`
   and `render_data_template` emit `build_surface("HtmlDocument", {...})` with inline
   `html` (< 50 KB) or `srcUrl` (signed artifact URL). SSR/PDF renderers degrade to a
   titled link; `interactive-html` and the bundled UI embed a sandboxed `<iframe>`.

### Component Diagram

```
LLM ──InfographicResponse──▶ InfographicToolkit.render()
                               │  ├─ InfographicHTMLRenderer.render_to_html()  (unchanged)
                               │  ├─ _persist()  → artifact_id, html_url
                               │  └─ _build_a2ui_envelope()  ← ALWAYS (emit_a2ui=True)
                               │        └─ adapters.infographic_response_to_envelope()  [parity fields]
                               ▼
                    InfographicRenderResult{html_url, html_inline, a2ui_envelope, …}
                               │
        PandasAgent.ask() / BaseBot post-loop ──┬─ output_mode==A2UI ──▶ finalize_a2ui_response + metadata.html_url
                                                └─ else ──▶ _finalize_infographic_response + response.a2ui_envelope
                               ▼
        AgentTalk.post ──┬─ A2UI  → {output_mode:"a2ui", a2ui_envelope, metadata{html_url,…}}
                         └─ INFOGRAPHIC → {output_mode:"infographic", output:<html|url>, a2ui_envelope, metadata{…}}
                               ▼
   bundled UI: InfographicCanvas ── mode:"a2ui" → A2UIInfographic.svelte (features.a2ui)
                                 └─ mode:"html" → <iframe> (unchanged fallback / toggle)
   navigator-frontend-next: consumes a2ui_envelope (unchanged contract)

Jinja lane: render_template / render_data_template ─▶ TemplateEngine ─▶ HTML artifact
                                                    └▶ build_surface("HtmlDocument", {html|srcUrl, title})
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `InfographicToolkit` (`parrot/tools/infographic_toolkit.py`) | modifies | `emit_a2ui` default → `True`; `render_template`/`render_data_template` build `HtmlDocument` surfaces |
| `get_infographic_html_renderer` (`parrot/outputs/formats/__init__.py`) | modifies | remove unconditional `DeprecationWarning`; docstring re-worded to "HTML sibling of the A2UI lane" |
| `PandasAgent.ask()` post-loop (`parrot/bots/data.py`) | modifies | dual-emit routing rule (Overview step 2) |
| `BaseBot` finalizer (`parrot/bots/base.py`) | modifies | same rule |
| `AgentTalk._format_infographic_response` / A2UI early return (`handlers/agent.py`) | modifies | `a2ui_envelope` on INFOGRAPHIC envelope; `metadata` on A2UI envelope |
| `adapters/infographic.py` | modifies | forward presentation fields; update `CHART_TYPE_MAP`; `layout` |
| `parrot.models.outputs.ChartType` / `StructuredChartConfig` | extends | 5 new chart types (schema derived via `derive_schema`, so `Chart` schema follows) |
| `catalog/parrot/chart.py`, `datatable.py`, `kpicard.py`, `infographic.py` | extends | additive props; `Infographic.lower()` honours `layout` |
| `catalog/__init__.py::register_component` + `catalog/base.py` | extends | new `tool_only: bool = False` gate (D10b-style) |
| `catalog/parrot/htmldocument.py` (new) | creates | `HtmlDocument` component |
| `a2ui_renderers/echarts.py`, `interactive_html.py`, `ssr_html.py`, `pdf.py` (visualizations) | extends | new chart types / `HtmlDocument` handling / degradation |
| `ui/src/lib/components/agents/canvas/InfographicCanvas.svelte`, `AgentChat.svelte`, `infographic-types.ts`, `features.ts`, `vite.config.ts` | modifies | `mode:"a2ui"`, envelope detection, `features.a2ui` flag |
| `ui/src/lib/components/agents/canvas/a2ui/*` (new) | creates | Svelte A2UI Infographic renderer + binding resolver |
| `docs/outputs/a2ui-v1.md`, `docs/toolkits/infographic_toolkit.md`, `docs/infographic_handler_api.md`, `docs/frontend/agentdashboard-a2ui-reference.md`, `sdd/specs/a2ui-implementation.spec.md` (G7 note) | docs | contract + policy amendment |

### Data Models

```python
# parrot/tools/infographic_toolkit.py — UNCHANGED shape (already carries the envelope)
class InfographicRenderResult(BaseModel):
    artifact_id: str
    html_url: str
    html_inline: Optional[str] = None
    template_name: str
    theme: Optional[str] = None
    data_variables: List[str] = Field(default_factory=list)
    enhanced: bool = False
    a2ui_envelope: Optional[Dict[str, Any]] = None   # now populated by default

# AgentTalk INFOGRAPHIC JSON envelope — ADDITIVE key
{
  "input": "...", "output": "<html_inline | html_url>", "response": "<explanation>",
  "output_mode": "infographic", "artifact_id": "infographic-<12hex>",
  "data": [...], "metadata": {"html_url": "...", "template_name": "...", "theme": "...", ...},
  "a2ui_envelope": {"version": "v1.0", "createSurface": {...}}   # NEW (omitted when build failed)
}

# AgentTalk A2UI JSON envelope — ADDITIVE metadata
{
  "input": "...", "output": "<explanation>", "output_mode": "a2ui",
  "a2ui_envelope": {...},
  "metadata": {"html_url": "...", "artifact_id": "...", "template_name": "...", "theme": "..."}  # NEW
}

# HtmlDocument component props (JSON Schema, catalog/parrot/htmldocument.py)
{
  "type": "object",
  "properties": {
    "title":  {"type": "string"},
    "html":   {"type": "string", "description": "Trusted, fully rendered HTML document (inline when < 50 KB)."},
    "srcUrl": {"type": "string", "description": "Signed artifact URL when the document is too large to inline."},
    "theme":  {"type": "string"}
  },
  "required": ["title"],
  "oneOf": [{"required": ["html"]}, {"required": ["srcUrl"]}]
}

# Frontend (infographic-types.ts) — ADDITIVE
export interface InfographicTabData {
  mode: "json" | "html" | "a2ui";      // "a2ui" NEW
  html?: string; url?: string;
  infographic?: InfographicData;
  envelope?: A2UIEnvelope;             // NEW: {"version":"v1.0","createSurface":{...}}
  query?: string; template?: string; theme?: string;
}
```

### New Public Interfaces

```python
# parrot/outputs/a2ui/catalog/__init__.py — additive keyword
def register_component(name: str, *, requires_actions: bool = False,
                       catalog_id: str = DEFAULT_CATALOG_ID, is_primitive: bool = False,
                       allowed_parents: list[str] | None = None,
                       allowed_children: list[str] | None = None,
                       tool_only: bool = False) -> Callable[[type], type]: ...
# validate_envelope(...): an LLM-origin envelope containing a tool_only component raises
# CatalogValidationError (same mechanism as the requires_actions D10b gate).

# parrot/outputs/a2ui/catalog/parrot/htmldocument.py
@register_component("HtmlDocument", allowed_parents=["root", "Column"], tool_only=True)
class HtmlDocumentComponent:
    SCHEMA: dict; INSTRUCTIONS: str
    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:
        """Text placeholder '[HTML document: <title>]' with metadata.extensions
        {'parrot_role': 'html_document', 'parrot_src_url': <srcUrl|None>} so static
        renderers degrade to a titled link."""

# parrot/outputs/a2ui/builders.py — additive
def build_html_document(*, title: str, html: str | None = None, src_url: str | None = None,
                        theme: str | None = None, surface_id: str = "html-document",
                        metadata: dict | None = None) -> CreateSurface: ...

# parrot/tools/infographic_toolkit.py
class InfographicToolkit(AbstractToolkit):
    def __init__(self, artifact_store, *, ..., emit_a2ui: bool = True, ...): ...   # default flipped
    def _build_html_document_envelope(self, *, html: str, html_url: str, artifact_id: str,
                                      title: str, theme: str | None) -> dict | None: ...
```

```ts
// ui/src/lib/components/agents/canvas/a2ui/
export function resolveBinding(value: unknown, dataModel: Record<string, unknown>): unknown; // {"path": "/a/b"} → value
export function inferSurfaceKind(surface: CreateSurface): "widget" | "infographic" | "dashboard"; // docs §6.2 heuristic
// A2UISurface.svelte      props: { envelope: A2UIEnvelope }         — root dispatcher
// A2UIInfographic.svelte  props: { component, dataModel }           — title/subtitle/sections → tabs
// A2UINode.svelte         props: { descriptor, dataModel }          — Chart | DataTable | KPICard | InfoCard |
//                                                                     Timeline | Text | Image | List | CheckBox |
//                                                                     Divider | Tabs | Row | Column | HtmlDocument
```

---

## 3. Module Breakdown

### Module 1: Backend dual-emit by default (G1, G2, G6)
- **Path**: `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py`,
  `packages/ai-parrot/src/parrot/outputs/formats/__init__.py`,
  `packages/ai-parrot/src/parrot/bots/data.py`, `packages/ai-parrot/src/parrot/bots/base.py`,
  `packages/ai-parrot-server/src/parrot/handlers/agent.py`
- **Responsibility**: flip `emit_a2ui` default; remove the unconditional
  `DeprecationWarning` in `get_infographic_html_renderer()` (keep the `ImportError`
  translation); implement the dual-emit routing rule in both bot finalizers; add
  `a2ui_envelope` to the INFOGRAPHIC envelope and `metadata` to the A2UI early return;
  keep the no-stream gate for INFOGRAPHIC. `InfographicAuthoringMixin`,
  `InfographicTalk._get_render_toolkit`, `ResultAgent` need no code change (they inherit
  the default) — add regression tests proving they now emit.
- **Depends on**: none.

### Module 2: A2UI presentation parity (G3)
- **Path**: `packages/ai-parrot/src/parrot/models/outputs.py` (`ChartType`,
  `StructuredChartConfig`), `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/{chart,datatable,kpicard,infographic}.py`,
  `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py`,
  `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/{echarts,interactive_html,ssr_html}.py`,
  `packages/ai-parrot/tests/outputs/a2ui/golden/*.json`
- **Responsibility**:
  1. `ChartType` Literal += `gauge`, `funnel`, `waterfall`, `heatmap`, `treemap`
     (schema parity by construction via `derive_schema`). `CHART_TYPE_MAP` becomes
     identity for all 12 legacy types except `horizontalBar` handling
     (`ChartBlock.layout`/orientation → `horizontalBar` where the block says so);
     `donut`/`radar` stop collapsing.
  2. Adapter `_chart()` forwards `color_by_sign`, `positive_color`, `negative_color`,
     `palette`/per-series colours, `trendline`, `x_axis_mode`, `layout` (verify the
     exact camelCase/snake_case key names the derived `CHART_SCHEMA` exposes before
     writing them — see §7). `_table()` forwards `style`; `_hero_card()` forwards
     `icon`, `color`, `comparison_period`; bullet `columns` → `List` descriptor
     `metadata.extensions.parrot_columns`.
  3. `Chart` schema += `layout` enum `["full","half"]`; `DataTable` += `style`;
     `KPICard` += `icon`, `color`, `comparisonPeriod`. `InfographicComponent.lower()`
     groups consecutive `layout=="half"` children into a `Row`.
  4. ECharts renderer: native `gauge`/`funnel`/`waterfall` (stacked-bar technique)/
     `heatmap`/`treemap` options. `interactive-html` (Chart.js) and `ssr-html`: degrade
     unsupported types to `bar` **with** a `metadata["degraded"]` entry (never silent).
  5. Regenerate `chart_lowered.json`, `kpicard_lowered.json`, `datatable_lowered.json`,
     `infographic_lowered.json` goldens and record the diff in the task's completion note.
- **Depends on**: none (parallel-safe with Module 1 at file level; sequential in the worktree).

### Module 3: Bundled-UI A2UI Infographic renderer (G4)
- **Path**: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/`
  (new: `A2UISurface.svelte`, `A2UIInfographic.svelte`, `A2UINode.svelte`,
  `a2ui-types.ts`, `a2ui-binding.ts`, `a2ui-kind.ts`, `*.test.ts`),
  `.../canvas/InfographicCanvas.svelte`, `.../canvas/infographic/infographic-types.ts`,
  `.../canvas/infographic/InfographicToolbar.svelte`, `.../agents/AgentChat.svelte`,
  `ui/src/lib/features.ts`, `ui/vite.config.ts`, `ui/src/lib/types/generated/AgentChatResponse.d.ts`
  (regenerated via `pnpm generate` if the backend schema changes)
- **Responsibility**: `features.a2ui` flag (`PUBLIC_AGENTCHAT_A2UI`, default `true`,
  same `agentchatDefines` pattern); `InfographicTabData.mode = "a2ui"` + `envelope`;
  `maybeOpenInfographicCanvas` prefers `a2ui` mode when `message.a2ui_envelope` has an
  `Infographic`/`Report` root and `features.a2ui`, else current HTML logic; toolbar toggle
  "Rendered / HTML" (HTML view = existing iframe via `metadata.html_url`); `A2UINode`
  dispatch for the display primitives and Parrot composites listed in §2 New Public
  Interfaces; JSON-pointer binding resolution; `HtmlDocument` → sandboxed `<iframe
  srcdoc|src sandbox="allow-scripts">`; action-bearing/unknown components → visible
  placeholder. Reuse the existing ECharts usage of `InfographicChartBlock.svelte` by
  mapping `Chart` props + bound rows to its `ChartBlockData` shape (adapter in
  `A2UINode`), rather than a second chart stack.
- **Depends on**: Module 1 (envelope present on INFOGRAPHIC turns), Module 2 (prop names),
  Module 4 (`HtmlDocument` shape).

### Module 4: `HtmlDocument` opaque HTML surface for the Jinja lane (G5)
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py`,
  `.../catalog/base.py`, `.../catalog/parrot/htmldocument.py` (new),
  `.../catalog/parrot/__init__.py`, `.../a2ui/builders.py`,
  `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` (`render_template`,
  `render_data_template`), `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/{ssr_html,pdf,interactive_html,adaptive_cards}.py`
- **Responsibility**: `tool_only` registration gate + `validate_envelope` enforcement for
  `Origin.LLM`; `HtmlDocumentComponent` + `build_html_document()`; toolkit
  `_build_html_document_envelope()` replaces the synthetic title+summary envelope in
  `render_template` (lines 613-630) and the descriptor-less path of `render_data_template`
  (a supplied `SectionDescriptor` keeps today's descriptor-layout envelope — FEAT-326);
  renderer handling: `interactive-html` embeds sandboxed iframe (inline `srcdoc` or
  `src`), `ssr-html`/`pdf`/`adaptive_cards` degrade to titled link + `degraded` entry.
  Security stance (resolved): content is trusted developer-template output; no
  re-sanitisation server-side; the frontend/interactive renderer MUST sandbox the iframe;
  LLM-origin envelopes cannot carry `HtmlDocument`.
- **Depends on**: Module 1 (default emit).

### Module 5: Policy amendment, docs, smoke evidence
- **Path**: `sdd/specs/a2ui-implementation.spec.md` (G7 amendment note, one paragraph
  referencing FEAT-527), `docs/outputs/a2ui-v1.md`, `docs/toolkits/infographic_toolkit.md`,
  `docs/infographic_handler_api.md` (also fix the stale `packages/ai-parrot/…/handlers/infographic.py`
  path noted in `docs/frontend/agentdashboard-a2ui-reference.md` §11.14),
  `docs/frontend/agentdashboard-a2ui-reference.md` (§6.1 "Infographic" row: envelope now
  present on `output_mode: infographic` turns too; `HtmlDocument`), `examples/agents/a2ui/README.md`,
  `artifacts/logs/feat-527-*.log`
- **Responsibility**: document the dual-emit contract and the amended G7 ("legacy HTML
  infographic lane is a permanent sibling emission of the A2UI lane; other legacy
  OutputModes remain deprecated"); smoke script driving `InfographicToolkit.render()` +
  `render_template()` offline and asserting both emissions; save evidence.
- **Depends on**: Modules 1-4.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_toolkit_default_emits_a2ui` | 1 | `InfographicToolkit(artifact_store=…)` → `_emit_a2ui is True`; `render()` result has `a2ui_envelope` |
| `test_toolkit_emit_a2ui_false_still_supported` | 1 | explicit `emit_a2ui=False` yields `a2ui_envelope is None` |
| `test_get_infographic_html_renderer_no_deprecation_warning` | 1 | `warnings.catch_warnings(record=True)` → no `DeprecationWarning` |
| `test_pandasagent_infographic_dual_emit_default_mode` | 1 | envelope present + `output_mode!=A2UI` → `OutputMode.INFOGRAPHIC`, `output` is HTML, `response.a2ui_envelope` set (extends `tests/unit/bots/test_pandasagent_infographic.py`) |
| `test_pandasagent_infographic_a2ui_mode_metadata` | 1 | `output_mode=A2UI` → `finalize_a2ui_response` + `metadata.html_url/artifact_id` |
| `test_basebot_infographic_dual_emit` | 1 | same two rules on `BaseBot` |
| `test_agenttalk_infographic_envelope_has_a2ui` | 1 | `_format_infographic_response` JSON includes `a2ui_envelope`; absent when `None` (extends `tests/handlers/test_infographic_handler.py`) |
| `test_agenttalk_a2ui_response_has_html_metadata` | 1 | A2UI early return includes `metadata.html_url` |
| `test_agenttalk_infographic_streaming_still_disabled` | 1 | `use_stream` forced `False` for INFOGRAPHIC |
| `test_authoring_mixin_toolkit_emits_a2ui` | 1 | `InfographicAuthoringMixin`-built toolkit emits by default |
| `test_chart_type_literal_extended` | 2 | `StructuredChartConfig(type="gauge")` validates; `CHART_SCHEMA["properties"]["type"]["enum"]` contains the 5 new types |
| `test_adapter_chart_forwards_presentation_fields` | 2 | `color_by_sign`, colours, `palette`, `trendline`, `layout` reach the `Chart` descriptor; `donut`/`radar` preserved |
| `test_adapter_hero_card_forwards_icon_color_period` | 2 | `KPICard` descriptor carries `icon`, `color`, `comparisonPeriod` |
| `test_adapter_table_forwards_style` | 2 | `DataTable` descriptor carries `style` |
| `test_infographic_lower_half_layout_row` | 2 | two consecutive `layout:"half"` charts lower into one `Row` (golden regenerated) |
| `test_echarts_new_chart_types` | 2 | option JSON for gauge/funnel/waterfall/heatmap/treemap built from bound rows |
| `test_interactive_html_degrades_unsupported_chart_types` | 2 | `metadata["degraded"]` entry recorded; output still renders `bar` |
| `test_htmldocument_registration_tool_only` | 4 | LLM-origin `validate_envelope` raises `CatalogValidationError`; tool origin passes |
| `test_htmldocument_lower_placeholder` | 4 | lowers to `Text` + `parrot_role: html_document` |
| `test_build_html_document_inline_vs_url` | 4 | `html` when < 50 KB else `srcUrl`; `oneOf` enforced |
| `test_render_template_emits_htmldocument` | 4 | `render_template()` envelope root is `HtmlDocument` (replaces synthetic blocks); `render_data_template` with descriptor unchanged |
| `test_ssr_html_htmldocument_degrades_to_link` | 4 | SSR output contains titled link, `degraded` entry |
| `test_interactive_html_htmldocument_iframe_sandboxed` | 4 | `<iframe … sandbox=` present; no inline execution of document scripts in host page |
| `a2ui-binding.test.ts` | 3 | `{"path":"/charts/chart-0/rows"}` resolves; missing path → `undefined`; non-binding passthrough |
| `a2ui-kind.test.ts` | 3 | docs §6.2 heuristic: `Infographic` 1 section → infographic; >1 → dashboard; `Chart` root → widget |
| `A2UIInfographic.test.ts` | 3 | renders title/subtitle; N sections → N tabs; nested KPICard/Chart/DataTable/Text/List/Divider; unknown component → placeholder |
| `A2UINode.htmldocument.test.ts` | 3 | `HtmlDocument` renders sandboxed iframe with `srcdoc` or `src` |
| `AgentChat.a2ui-canvas.test.ts` | 3 | message with `a2ui_envelope` (Infographic root) opens tab `mode:"a2ui"`; with flag off → existing HTML path; `output_mode:"a2ui"` without html → still opens |
| `features.test.ts` (extend) | 3 | `features.a2ui` defined; `PUBLIC_AGENTCHAT_A2UI=false` → `false` |

### Integration Tests
| Test | Description |
|---|---|
| `test_infographic_dual_emit_end_to_end` | offline `PandasAgent` + `InfographicToolkit` (as in `tests/tools/test_infographic_toolkit_a2ui_wiring.py` fixture style) → `AIMessage` carries HTML `output`, `OutputMode.INFOGRAPHIC`, `a2ui_envelope` validating against the Parrot catalog |
| `test_agenttalk_infographic_json_contract` | handler-level: INFOGRAPHIC JSON body has every documented key **plus** `a2ui_envelope`; `Accept: text/html` body unchanged |
| `test_render_template_htmldocument_end_to_end` | toolkit with in-memory Jinja template → artifact persisted, envelope root `HtmlDocument`, `srcUrl == html_url` when large |
| `test_goldens_regenerated_consistently` | every `tests/outputs/a2ui/golden/*.json` matches current `lower()` output (existing harness) |
| `vitest run` (ui) | whole SPA suite green incl. new `a2ui/*.test.ts` |

### Test Data / Fixtures
```python
# Reuse tests/tools/test_infographic_toolkit_a2ui_wiring.py::_response() (title, summary, hero_card, chart, table)
# and its "toolkit without __init__" fixture; add a financial_variance-shaped response:
@pytest.fixture
def variance_response() -> InfographicResponse:
    return InfographicResponse(template="financial_variance", theme="corporate", blocks=[
        {"type": "title", "title": "Q3 Variance"},
        {"type": "chart", "chart_type": "bar", "layout": "half", "color_by_sign": True,
         "labels": ["A", "B"], "series": [{"name": "delta", "values": [10, -4]}]},
        {"type": "chart", "chart_type": "donut", "layout": "half",
         "labels": ["x", "y"], "series": [{"name": "share", "values": [60, 40]}]},
        {"type": "table", "style": "striped", "columns": [{"key": "k", "label": "K"}], "rows": [{"k": 1}]},
        {"type": "hero_card", "label": "Revenue", "value": "$1.2M", "icon": "💰", "comparison_period": "vs Q2"},
    ])
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `InfographicToolkit(artifact_store=…)` emits `a2ui_envelope` by default; `emit_a2ui=False` still opts out (G1)
- [ ] `get_infographic_html_renderer()` emits no `DeprecationWarning`; the `ImportError` translation for a missing satellite is preserved (G1, G6)
- [ ] `PandasAgent.ask()` and `BaseBot` apply the dual-emit rule: default → `OutputMode.INFOGRAPHIC` + HTML `output` + `a2ui_envelope`; requested `A2UI` → `finalize_a2ui_response` + `metadata.html_url`/`artifact_id` (G2)
- [ ] `AgentTalk` INFOGRAPHIC JSON envelope is byte-identical to today's plus one additive `a2ui_envelope` key; `Accept: text/html` path and CSP headers unchanged; streaming still disabled for INFOGRAPHIC (G2, G6)
- [ ] `AgentTalk` A2UI early return carries `metadata` with `html_url` when an infographic artifact exists (G2)
- [ ] `ChartType` accepts `gauge`, `funnel`, `waterfall`, `heatmap`, `treemap`; `CHART_TYPE_MAP` no longer collapses `donut`/`radar`; ECharts renders the 5 new types; Chart.js/SSR degrade with a recorded `degraded` entry (G3)
- [ ] Adapter forwards `color_by_sign`, `positive_color`, `negative_color`, `palette`, `trendline`, `x_axis_mode`, `layout`, table `style`, hero-card `icon`/`color`/`comparison_period`; `Infographic.lower()` groups `half` siblings in a `Row`; goldens regenerated and diff recorded (G3)
- [ ] `HtmlDocument` is registered `tool_only`; an LLM-origin envelope containing it fails `validate_envelope`; `render_template` / descriptor-less `render_data_template` emit it (inline `html` < 50 KB else `srcUrl`) (G5)
- [ ] `interactive-html` embeds `HtmlDocument` in a sandboxed iframe; `ssr-html`/`pdf`/`adaptive_cards` degrade to a titled link (G5)
- [ ] Bundled UI: `features.a2ui` flag exists; a chat turn with an `Infographic`-rooted `a2ui_envelope` opens the canvas in `mode:"a2ui"` and renders title, sections-as-tabs, KPICard, Chart, DataTable, Text, List, Divider, Image, Timeline, InfoCard, HtmlDocument; toolbar toggles to the HTML iframe view; flag off → today's behaviour (G4)
- [ ] `FlexDashboard`, `RecipeRunner`, `ui_surfaces` and navigator-frontend-next contracts unchanged (no diff under `agents/flex_dashboard*`, `tools/infographic_recipes/`, `handlers/ui_surfaces.py`) (Non-Goals)
- [ ] All unit tests pass: `timeout -s KILL 600 pytest packages/ai-parrot/tests/unit packages/ai-parrot/tests/tools packages/ai-parrot/tests/handlers packages/ai-parrot/tests/outputs -q`; visualizations + server suites green; `cd packages/ai-parrot-server/ui && pnpm test`
- [ ] Docs updated (§3 Module 5) and G7 amendment paragraph added to `sdd/specs/a2ui-implementation.spec.md`
- [ ] No breaking change to any existing public API; only additive keys/props/flags

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified on `dev @ aa84e1838` (2026-09-04).
> Implementation agents MUST NOT reference imports, attributes, or methods not listed
> here without first verifying they exist via `grep` or `read`.

### Verified Imports
```python
from parrot.tools.infographic_toolkit import InfographicToolkit, InfographicRenderResult   # infographic_toolkit.py:159,180
from parrot.models.infographic import InfographicResponse, InfographicBlock, ThemeConfig, theme_registry, JSBundle, BlockType, ChartType  # models/infographic.py:1027,1290,1563,1118,79,103
from parrot.models.infographic_templates import InfographicTemplate, BlockSpec, infographic_registry  # models/infographic_templates.py:47,21,587
from parrot.models.outputs import OutputMode, StructuredChartConfig, ChartType as A2UIChartType  # models/outputs.py:58/64, 319, 309 (Literal)
from parrot.models.responses import AIMessage                                    # models/responses.py:72
from parrot.outputs.formats import get_infographic_html_renderer                # outputs/formats/__init__.py:119
from parrot.outputs.a2ui.adapters import infographic_response_to_envelope, CHART_TYPE_MAP  # adapters/__init__.py:12-15
from parrot.outputs.a2ui.builders import build_infographic, build_surface       # builders.py:216 (build_surface used at :242)
from parrot.outputs.a2ui.emission import finalize_a2ui_response                 # emission.py:18
from parrot.outputs.a2ui.serialization import serialize                        # used at infographic_toolkit.py:_build_a2ui_envelope
from parrot.outputs.a2ui.catalog import get_component, register_component       # catalog/__init__.py:107 (register_component)
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree, CatalogValidationError, TabSpec, DEFAULT_CATALOG_ID  # catalog/base.py:97,141,53
from parrot.outputs.a2ui.catalog.basic import BASIC_CATALOG_ID                  # catalog/basic/__init__.py:44
from parrot.outputs.a2ui.models import Component, CreateSurface                 # used by catalog/parrot/infographic.py:31, renderers/__init__.py:26
from parrot.outputs.a2ui.renderers import AbstractA2UIRenderer, RendererCapabilities, get_a2ui_renderer, register_a2ui_renderer  # renderers/__init__.py:78,51,141,108
from parrot.outputs.a2ui.artifacts import RenderedArtifact                     # artifacts.py:54
from parrot.bots.mixins.infographic_authoring import InfographicAuthoringMixin  # bots/mixins/infographic_authoring.py (class body :60-100)
from parrot.tools.infographic_sections import SectionDescriptor                 # tools/infographic_sections.py:80
```
Satellite (`ai-parrot-visualizations`, PEP 420 merge — import paths unchanged):
```python
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer     # formats/infographic_html.py:223 (@register_renderer(OutputMode.INFOGRAPHIC))
from parrot.outputs.formats.infographic import InfographicRenderer, INFOGRAPHIC_SYSTEM_PROMPT  # formats/infographic.py:138,16
from parrot.outputs.formats.assets.design_system import DesignSystem            # design_system/__init__.py:79
# renderers self-register on import: parrot.outputs.a2ui_renderers.{ssr_html,interactive_html,pdf,echarts,folium_map,adaptive_cards}
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py
class InfographicRenderResult(BaseModel):                       # :159
    artifact_id: str; html_url: str; html_inline: Optional[str] = None; template_name: str
    theme: Optional[str] = None; data_variables: List[str]; enhanced: bool = False
    a2ui_envelope: Optional[Dict[str, Any]] = None              # :172
class InfographicToolkit(AbstractToolkit):                       # :180
    def __init__(self, artifact_store, *, ..., template_dirs=None, templates=None,
                 emit_a2ui: bool = False, ...) -> None            # :213-219 ; self._emit_a2ui = emit_a2ui  :252
        self._renderer = get_infographic_html_renderer()()       # :253  (deprecated-warning trip site)
        self._template_engine: Optional[TemplateEngine]         # :260-264
    async def render(self, template_name: str, theme: Optional[str], ...) -> InfographicRenderResult  # :402
        # render_to_html :466 · _maybe_enhance :484 · _persist :493 · if self._emit_a2ui: _build_a2ui_envelope :508-514
    async def render_template(self, template_name: str, data=None, theme=None, title=None) -> InfographicRenderResult  # :524
        # emit_a2ui branch builds synthetic title+summary InfographicResponse :613-630  ← REPLACED by HtmlDocument (Module 4)
    async def render_data_template(self, ..., descriptor: Optional[SectionDescriptor] = None, ...)  # :643-647
    def _build_a2ui_envelope(self, response: InfographicResponse, artifact_id: str, *, title=None) -> Optional[Dict]  # :846
    async def _persist_template(...)  # :1018 ;  async def _persist(...)  # :1929
_INLINE_THRESHOLD  # module constant, 50 KB (:81 comment)

# packages/ai-parrot/src/parrot/outputs/formats/__init__.py
_A2UI_REPLACEMENTS: dict[OutputMode, str]                        # :15-27 (INFOGRAPHIC intentionally absent)
def _warn_if_deprecated(mode: OutputMode) -> None                # :30
RENDERERS[OutputMode.INFOGRAPHIC] = (".infographic", ".infographic_html")  # :69
def get_infographic_html_renderer()                              # :119 ; warnings.warn(... DeprecationWarning) :133-139 ← REMOVE

# packages/ai-parrot/src/parrot/bots/data.py  (PandasAgent.ask post-loop)
infographic_envelope = self._extract_last_infographic_result(response.tool_calls)   # :1880
if getattr(infographic_envelope, "a2ui_envelope", None) is not None: ... finalize_a2ui_response(response); return response  # :1890-1898 ← REWORK
explanation = self._finalize_infographic_response(response, infographic_envelope)   # :1899 ; def at :1000

# packages/ai-parrot/src/parrot/bots/base.py
def _finalize_infographic_response(self, response, envelope)     # docstring :895 ; sets output/output_mode/artifact_id :908-910
if getattr(infographic_envelope, "a2ui_envelope", None) is not None: response.a2ui_envelope = ...; finalize_a2ui_response(response)  # :1426-1428 ← REWORK
elif output_mode == OutputMode.INFOGRAPHIC: warning + fallback to DEFAULT       # :1436-1442

# packages/ai-parrot-server/src/parrot/handlers/agent.py  (AgentTalk)
if output_mode in (OutputMode.INFOGRAPHIC, OutputMode.INTERACTIVE): use_stream = False   # :1625-1628 (KEEP)
if getattr(response, "output_mode", None) == OutputMode.A2UI: return self.json_response({input, output, output_mode, a2ui_envelope})  # :2733-2741 ← add metadata
if getattr(response, "output_mode", None) == OutputMode.INFOGRAPHIC: return self._format_infographic_response(...)  # :2745-2755
_a2ui_envelope passthrough on generic path (FEAT-473 G9)          # :2834-2840 (pattern to mirror)
@staticmethod def _extract_infographic_explanation(response) -> str   # :3023
def _format_infographic_response(self, response, format_kwargs, user_id=None, user_session=None, response_time_ms=None, agent_name=None, session_id=None, client_message_id=None) -> web.Response  # :3052 ; obj_response dict :3118-3135

# packages/ai-parrot/src/parrot/bots/abstract.py
async def get_infographic(self, question, template=None, ..., theme=None, accept="text/html", ctx=None, **kwargs) -> AIMessage  # :3952 (uses get_infographic_html_renderer :4048; sets OutputMode.HTML :4058)

# packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py
class InfographicAuthoringMixin: def __init__(self, *args, infographic_toolkit=None, artifact_store=None, recipe_store=None, template_dirs=None, **kwargs)  # :75-82 ; builds InfographicToolkit(...) without emit_a2ui :85-89
# consumers: parrot/bots/info.py:37 InfoAgent(NarrativeMixin, InfographicAuthoringMixin, Agent); agents/flex_dashboard.py:127 FlexDashboard(NarrativeMixin, InfographicAuthoringMixin, PandasAgent)

# packages/ai-parrot-server/src/parrot/handlers/infographic.py
class InfographicTalk(AgentTalk)                                  # :72
def _get_render_toolkit(self) -> InfographicToolkit              # :497 ; InfographicToolkit(artifact_store=app.get("artifact_store"), template_dirs=template_dirs) :535-538
def _negotiate_accept(self) -> str                               # :819
# packages/ai-parrot/src/parrot/bots/flows/result_agent.py: InfographicToolkit(artifact_store=self._artifact_store)  # :142, :171
# packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py: InfographicToolkit(artifact_store=artifact_store, **params)  # :436

# packages/ai-parrot/src/parrot/models/outputs.py
ChartType = Literal["bar","horizontalBar","line","area","scatter","pie","donut","radar","map"]   # :309-312
class StructuredChartConfig(BaseModel):                          # :319
    type: ChartType; x: str; y: List[str]; stacked: Optional[bool]; trendline: Optional[bool]; split_series; show_legend
    x_axis_mode: Optional[XAxisMode]; palette: Optional[List[str]]; color_by_sign: Optional[bool]; negative_color; positive_color  # :344-376
class OutputMode(Enum): HTML="html" :41 ; INFOGRAPHIC="infographic" :58 ; INTERACTIVE="interactive" :59 ; A2UI="a2ui" :64

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel): output_mode: OutputMode :220 ; artifact_id: Optional[str] :224 ; a2ui_envelope: Optional[Dict[str, Any]] :232

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py
def register_component(name: str, *, requires_actions: bool = False, catalog_id: str = DEFAULT_CATALOG_ID, is_primitive: bool = False, allowed_parents: list[str] | None = None, allowed_children: list[str] | None = None) -> Callable[[type], type]  # :107-115
# catalog/base.py: DEFAULT_CATALOG_ID :53 ; Origin enum (requires_actions enforcement) :86 ; BasicNode :97 ; TabSpec :141 ; registration record fields requires_actions/is_primitive/allowed_parents :245-247
# catalog/basic/__init__.py: BASIC_CATALOG_ID :44 ; 18 primitives registered via register_component(cls.__name__, catalog_id=BASIC_CATALOG_ID, is_primitive=True) :202
# catalog/parrot/__init__.py imports: datatable, chart, infographic, infocard, timeline, map, report, kpicard, filterbar (9 Parrot components)

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/infographic.py
INFOGRAPHIC_SCHEMA (title, subtitle, theme, sections[{heading, text, components[{component, properties}]}]) :33-63
@register_component("Infographic", allowed_parents=["root","Column"]) class InfographicComponent: def lower(self, component: Component, data_model: dict) -> BasicTree  # :144-181 ; >1 section → Tabs, else Column
# catalog/parrot/chart.py: CHART_SCHEMA derived from StructuredChartConfig via derive_schema, required ("type","x","y") :29
# catalog/parrot/kpicard.py schema props: label, value, unit, delta, trend(up|down|flat) :17-22
# catalog/parrot/datatable.py: required ("columns",) :30

# packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py
CHART_TYPE_MAP :83-96 (donut→pie, radar→line, funnel/waterfall/heatmap/treemap/gauge→bar) ; _CHART_FALLBACK="bar" :98
def _chart(self, block) -> dict  :235 (forwards title,type,x,y,stacked,showLegend,data binding only :256-264)
def _table(self, block) -> dict  :267 ; def _hero_card(self, block) -> dict :293
def infographic_response_to_envelope(response, *, surface_id="infographic", title=None) -> CreateSurface  # :599

# packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py
class RendererCapabilities(BaseModel) :51 ; class AbstractA2UIRenderer(ABC): async def render(self, envelope: CreateSurface, *, bake: bool = True) -> "Any | str" :78-89
def register_a2ui_renderer(name: str, capabilities: RendererCapabilities) :108 ; def get_a2ui_renderer(name: str) :141

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/
# echarts.py: honours stacked :147, palette :182-184, colorBySign (docstring :131-135)
# interactive_html.py: _INTERCEPTED = {"Chart","DataTable","Infographic","Map"} :120 ; def _render_infographic(self, props) :1136 ; Chart.js type map :160
# ssr_html.py: __init__(*, theme="light", layout="analytics") :150 ; DesignSystem.resolve/stylesheet :225-226 ; _render_<Primitive> methods :402-584 ; degrade() for unknown :388-393
# pdf.py: __init__(*, theme="light") → super().__init__(theme, layout="print") :113-126
# formats/assets/design_system/__init__.py: class DesignSystem :79 ; stylesheet(theme, layout) :95 ; resolve(envelope, *, theme_default, layout_default) :131

# packages/ai-parrot-server/ui/src
# lib/features.ts: features = Object.freeze({voice, avatar, maps, charts, canvas, infographic, datasets, richEditor}) :23-32
# vite.config.ts: agentchatDefines names [...,'INFOGRAPHIC','DATASETS','RICH_EDITOR'] :22-31 → __AGENTCHAT_<NAME>__ from PUBLIC_AGENTCHAT_<NAME>
# lib/components/agents/canvas/canvas-tab-manager.svelte.ts: CanvasTabType = "markdown"|"chart"|"spreadsheet"|"infographic"|"audio"|"interactive" :6-12 ; addTab(type, title, data=null): string :56
# lib/components/agents/canvas/infographic/infographic-types.ts: InfographicBlockType (12) :9-21 ; InfographicData :180-185 ; InfographicTabData {mode:"json"|"html", html?, url?, infographic?, query?, template?, theme?} :243-256
# lib/components/agents/canvas/InfographicCanvas.svelte: normalizeInfographicData :27-40 ; hasHtml/hasUrl/hasJson :46-52 ; iframe srcdoc :395-402 ; URL iframe :284-293
# lib/components/agents/AgentChat.svelte: effectiveOutputMode/isInfographic :993-1004 ; maybeOpenInfographicCanvas(message) :1847-1878 (opens only when output_mode==="infographic")
# lib/types/generated/AgentChatResponse.d.ts: a2ui_envelope?: A2UiEnvelope :47 (generated by `pnpm generate` — json2ts over ./schemas)
# package.json: "test": "vitest run" :14 ; "build": "pnpm generate && vite build" :12 ; svelte ^5.55, @testing-library/svelte ^5.4, vitest ^3.2

# tests to extend
# packages/ai-parrot/tests/tools/test_infographic_toolkit_a2ui_wiring.py (toolkit-without-__init__ fixture, _response())
# packages/ai-parrot/tests/unit/tools/test_infographic_toolkit.py ; tests/unit/bots/test_pandasagent_infographic.py ; tests/handlers/test_infographic_handler.py
# packages/ai-parrot/tests/outputs/a2ui/golden/{chart,datatable,filterbar,infocard,infographic,kpicard,map,report,timeline}_lowered.json
# packages/ai-parrot-server/tests/test_agenttalk_infographic_explanation.py ; ui: src/lib/features.test.ts, components/agents/features-gating.test.ts
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `InfographicToolkit.__init__(emit_a2ui=True)` | `render()` / `render_template()` / `render_data_template()` | `self._emit_a2ui` guard | `infographic_toolkit.py:252,508,613` |
| dual-emit rule | `PandasAgent.ask()` post-loop | replaces `:1890-1898` branch | `bots/data.py:1876-1910` |
| dual-emit rule | `BaseBot` finalizer | replaces `:1426-1428` branch | `bots/base.py:1425-1445` |
| `a2ui_envelope` key | `AgentTalk._format_infographic_response` | add to `obj_response` | `handlers/agent.py:3118-3135` |
| `metadata` on A2UI return | `AgentTalk.post` | extend dict | `handlers/agent.py:2733-2741` |
| `HtmlDocumentComponent` | catalog registry | `@register_component("HtmlDocument", allowed_parents=["root","Column"], tool_only=True)` + import in `catalog/parrot/__init__.py` | `catalog/__init__.py:107`, `catalog/parrot/__init__.py:18` |
| `build_html_document` | `build_surface` | same pattern as `build_infographic` | `builders.py:216-242` |
| `tool_only` gate | `validate_envelope` / `Origin` | same mechanism as `requires_actions` | `catalog/base.py:86,245` |
| new chart types | `CHART_SCHEMA` | `derive_schema(StructuredChartConfig)` — extend the Literal only | `catalog/parrot/chart.py:1-29`, `models/outputs.py:309` |
| ECharts new types | `EChartsRenderer` option builder | extend option construction | `a2ui_renderers/echarts.py:131-184` |
| `A2UISurface.svelte` | `InfographicCanvas.svelte` | `{#if tabData?.mode === 'a2ui' && features.a2ui}` | `InfographicCanvas.svelte:263` (json branch precedent) |
| `maybeOpenInfographicCanvas` | `canvasTabManager.addTab("infographic", title, tabData)` | tabData `mode:"a2ui"` | `AgentChat.svelte:1876` |
| `features.a2ui` | `vite.config.ts agentchatDefines` | append `'A2UI'` | `vite.config.ts:22-31`, `features.ts:23-32` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.outputs.infographic`~~ package — infographic renderers live in the **visualizations** satellite under `parrot.outputs.formats.infographic{,_html}`; models in `parrot.models.infographic{,_templates}`.
- ~~`parrot/outputs/a2ui/catalog/basic.py`~~ — `basic` is a **package** (`catalog/basic/__init__.py`, `functions.py`, `inputs.py`, `layout.py`, `media.py`).
- ~~`InfographicToolkit.emit_a2ui`~~ public attribute — it is the private `self._emit_a2ui`.
- ~~`InfographicRenderResult.html`~~ — fields are `html_inline` / `html_url`.
- ~~`HtmlDocument` component, `build_html_document()`, `register_component(tool_only=...)`~~ — created by Module 4.
- ~~`features.a2ui`, `__AGENTCHAT_A2UI__`, `canvas/a2ui/*`, `InfographicTabData.mode === "a2ui"`~~ — created by Module 3.
- ~~any A2UI renderer / `a2ui` import in `ui/src`~~ — only the generated `AgentChatResponse.d.ts` type mentions `a2ui_envelope`.
- ~~`get_a2ui_renderer("interactive_html")`~~ — registered name is `"interactive-html"` (hyphen); see doc §11.1 cold-registry caveat.
- ~~`Renderer.render_to_html()` on the base `Renderer` Protocol~~ — only `InfographicHTMLRenderer` has it; that is why `get_infographic_html_renderer()` exists.
- ~~a production `emit_a2ui=True` call site~~ — only `examples/agents/a2ui/a2ui_dashboard_walkthrough.py:197`.
- ~~`OutputMode.A2UI` streaming gate in `AgentTalk`~~ — only INFOGRAPHIC/INTERACTIVE are gated (`agent.py:1625`).
- ~~`UISurfaceKind.infographic` writes from `InfographicToolkit`~~ — persistence to `ui_surfaces` is the FEAT-492 REST lane, untouched here.
- ~~`?output_mode=` query parameter on the chat endpoint~~ — dead (doc §11.10); only the JSON body field works.
- ~~`agents.flex_dashboard.FlexDashboard` importable by dotted path~~ — regular-package shadowing; loaded via `AgentRegistry` file discovery (documented in `agents/flex_dashboard.py:19-40`).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Additive lane, never blocking** (FEAT-273 D1a): `_build_a2ui_envelope` failure logs a warning and degrades to HTML-only; keep that policy for the default-on path and for `HtmlDocument`.
- **Pure adapters** (spec G2): `adapters/infographic.py` stays deterministic — no clocks/uuids; new fields are passed through, not computed.
- **One-way import rule** (G8): `parrot.outputs.a2ui.*` never imports agents/clients/`DatasetManager`; the catalog imports only `parrot.models.*`.
- **Renderers stay in the satellite**; core ships contracts only. New chart types: ECharts option builders in `a2ui_renderers/echarts.py`; Chart.js fallbacks in `interactive_html.py` via the existing `degrade()` helper with `metadata["degraded"]`.
- **Schema parity by construction**: extend `StructuredChartConfig`/`ChartType` and let `derive_schema` regenerate `CHART_SCHEMA`; do not hand-edit the Chart JSON schema. **Verify the exact property key casing** the derived schema exposes (`showLegend` is camelCase in the adapter today at `:262`; `color_by_sign` may surface as `colorBySign` — echarts.py docstring uses `colorBySign`) before writing adapter keys.
- **AgentTalk envelope widening precedent**: mirror the FEAT-473 G9 block at `handlers/agent.py:2834-2840` (add key only when not `None`).
- **Frontend gating** (FEAT-476): every new import reached only through `if (features.a2ui) await import(...)`; markup under `{#if features.a2ui}`; flag via `PUBLIC_AGENTCHAT_A2UI`.
- **Frontend chart reuse**: map `Chart` props + resolved rows to the existing `ChartBlockData` and render with `InfographicChartBlock.svelte`; do not add a second charting dependency.
- **Golden fixtures**: regenerate with the existing harness under `tests/outputs/a2ui/golden/` and record the semantic diff in the completion note (FEAT-493 froze them for *its* scope; this feature legitimately changes `lower()` output for `Infographic`/`Chart`/`KPICard`/`DataTable`).
- Google-style docstrings, strict typing, `self.logger`, async-first, Pydantic models — repo standard.

### Known Risks / Gotchas
- **Double artefact in A2UI mode.** With `output_mode=A2UI`, `finalize_a2ui_response` writes a text fallback into `response.response` only when empty; the infographic explanation must be captured before `output` is overwritten (same aliasing gotcha documented at `base.py:899-902`). *Mitigation*: reuse `_extract_infographic_explanation` ordering; test both modes.
- **Envelope size on the chat JSON.** Chart/table rows are embedded in `dataModel` (adapter binds rows; row cap 1000 per doc §6.1). Large tables double the payload next to inline HTML. *Mitigation*: keep `html_inline` threshold logic; consider omitting `html_inline` when an envelope is present **only if** the frontend toggle can iframe `html_url` — decide in Module 1's task, default: keep both.
- **`HtmlDocument` is an HTML injection vector if LLM-authorable.** *Mitigation*: `tool_only=True` gate enforced in `validate_envelope` for `Origin.LLM`; sandboxed iframe on every interactive surface; content originates from trusted templates (TemplateEngine — confirm autoescape setting during Module 4 and record it).
- **`interactive-html` cold-registry bug** (doc §11.1): `get_a2ui_renderer("interactive-html")` fails until the module is imported. Not fixed here, but Module 4's renderer tests must import the module explicitly.
- **Frontend kind heuristic** is lossy (doc §6.2); `Report` roots also open the infographic canvas — acceptable for v1.
- **Deprecation removal is a policy change**: FEAT-273 §5 AC "replaced modes emit DeprecationWarning" no longer applies to the infographic-HTML path; Module 5 records the amendment in the FEAT-273 spec (one paragraph, no rewrite).
- **Chart.js has no native gauge/funnel/waterfall/heatmap/treemap**; the interactive lane will look poorer than ECharts for those. Documented degradation; not a blocker (U3 accepted "extend first, decide later").
- **Golden diff churn**: 4 fixtures change; reviewers must read the recorded diff rather than rubber-stamp regenerated JSON.
- **Shared main checkout**: all edits happen in the feature worktree (`.claude/worktrees/feat-FEAT-527-infographic-a2ui-migration`), never in the main tree.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| none new (backend) | — | ECharts bundle already vendored (`formats/assets/echarts.min.js`); Chart.js already vendored |
| none new (frontend) | — | Svelte 5 / vitest / @testing-library/svelte already in `ui/package.json` |

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — one worktree
  `.claude/worktrees/feat-FEAT-527-infographic-a2ui-migration` branched from `origin/dev`,
  tasks executed sequentially (`/sdd-start`).
- **Parallelism notes**: Modules 1 and 2 touch disjoint files and could run in parallel
  agents, but the per-feature policy keeps them sequential; Module 3 (frontend) depends on
  Modules 1, 2 and 4 for the final prop/envelope shapes and must come last before docs.
  Suggested order: 1 → 2 → 4 → 3 → 5.
- **Cross-feature dependencies**: none must merge first. Active worktrees
  `feat-FEAT-525-per-turn-conversation-compaction` and `feat-FEAT-523-pep-420-llm-clients`
  touch `parrot/memory`, `parrot/bots/abstract.py` (history) and `parrot/clients/*`; this
  feature must not edit `abstract.py` (its `get_infographic()` is a Non-Goal) to avoid
  merge friction.
- **Testing in the worktree**: follow the PYTHONPATH + compiled-`.so` copy procedure from
  the worktree-test-setup notes; wrap `pytest tests/unit` in `timeout -s KILL`.

---

## 8. Open Questions

> Resolved items are carried forward from the proposal verbatim; unresolved ones are
> spec/implementation-level.

- [x] **U1 — Target end state** — *Resolved in proposal*: Dual-emit permanently. Flip
  `emit_a2ui` default to `True`; keep the INFOGRAPHIC HTML envelope (`html_url` /
  `html_inline`) alongside `a2ui_envelope` for legacy consumers. FEAT-273 G7 must be
  amended; the unconditional DeprecationWarning must go. → §1 G1, §2 Overview 1-3, §3 M1/M5.
- [x] **U2 — Frontend of record** — *Resolved in proposal*: Both. navigator-frontend-next
  stays the primary A2UI consumer, and the bundled ai-parrot-server UI gains a minimal
  A2UI `Infographic` renderer as part of this feature. → §1 G4, §3 M3.
- [x] **U3 — Fate of templates/blocks** — *Resolved in proposal*: Extend A2UI
  presentation props first; `InfographicResponse` remains the LLM contract meanwhile;
  template→recipe re-expression deferred. → §1 G3 + Non-Goals, §3 M2.
- [x] **U4 — Jinja `render_template` lane** — *Resolved in proposal*: Wrap as opaque HTML
  surface (one envelope contract covers every infographic path). → §1 G5, §3 M4.
- [x] **Streaming gate under dual-emit** — *Resolved in spec*: keep the INFOGRAPHIC
  no-stream gate (signed URL must arrive atomically); A2UI-mode turns keep A2UI's
  behaviour. → §2 Overview 3, §5.
- [x] **Does FEAT-493 scope the HTML lane as long-lived?** — *Resolved in spec research*:
  yes — `html-renderer-design-system.spec.md:669` states the `formats/infographic_html.py`
  lane converges with the A2UI HTML renderers on one design system; consistent with
  dual-emit.
- [x] **What is on `origin/claude/a2ui-infografias-audit-wtp9eu` /
  `origin/claude/agenttalk-infographic-toolkit-0q473i`?** — *Resolved in spec research*:
  their commits (`1e6d741fc`, `575879c62`, `1180acf73`, `c76ee58a7`) are all ancestors of
  `dev`; nothing unmerged overlaps this feature.
- [ ] **Exact key casing of derived `CHART_SCHEMA` props** (`colorBySign` vs
  `color_by_sign`, etc.) — *Owner: Module 2 implementer* — read `derive_schema` output
  before writing adapter keys; record in the task completion note.
- [ ] **`TemplateEngine` autoescape default** — *Owner: Module 4 implementer* — confirm
  and record; if off, add `autoescape=True` for the infographic engine only.
- [ ] **Omit `html_inline` when an envelope is present?** — *Owner: Module 1 implementer /
  reviewer* — default is keep both (G6); revisit if chat payloads exceed 200 KB in smoke.
- [ ] **Should `AbstractBot.get_infographic()` (InfographicTalk lane) also attach an
  envelope?** — *Owner: product* — Non-Goal for FEAT-527; candidate follow-up.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-04 | Jesus Lara (via Claude Code) | Initial draft from `sdd/proposals/infographic-a2ui-migration.proposal.md`; FEAT-527 reserved via ledger |
