---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: A2UI rich visualizations — the `viz-core` grammar catalog, `Graph` with mermaid codec, live workflow surfaces

**Date**: 2026-09-05 (revision 2, same day)
**Author**: Jesus Lara (with Claude)
**Status**: accepted
**Recommended Option**: D (viz-core grammar catalog) for charts, plus Option B's `Graph` and `Timeline` v2 with `Graph` moved under viz-core, plus a tool-only vendor hint
**Builds on**: FEAT-527 `infographic-a2ui-migration` (chart-type parity), FEAT-470 `a2ui-v1-dialect` (wire + catalog), FEAT-469 `a2ui-agent-functions` (runtime RPC + SSE stream), FEAT-473 `a2ui-v1-structured-outputs` (schema parity by construction)
**Source artifacts (revision 2)**: `artifacts/a2ui/viz-core.catalog.json` (draft 0.1 of the viz-core catalog, official `catalog.json` shape) and `artifacts/a2ui/viz-core.example.jsonl` (a mixed-catalog `createSurface` + `updateDataModel` pair). Their eventual home is `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/viz_core/spec/`.

> **Revision 2 (2026-09-05).** Revision 1 recommended Option B: a typed `spec`
> discriminated union on the Parrot `Chart`, keyed on `type`. The two viz-core
> artifacts replace that axis with a **grammar-of-graphics catalog** (a frame with
> `Series` children, mark × field × semantic colour) in a **third A2UI catalog**.
> This revision records that change as Option D, keeps Option B for `Graph` and
> `Timeline` v2, moves `Graph` under viz-core, and re-sequences the three
> follow-on specs. Every decision taken in revision 1 that is not named below
> still stands (terminology, FEAT-470 invariants, SSE channel, drill-down path).

---

## Problem Statement

FEAT-527 makes every infographic turn emit an A2UI envelope and widens `ChartType`
with `gauge`, `funnel`, `waterfall`, `heatmap`, `treemap`. But the `Chart` catalog
component still describes every type with the same vocabulary: `type`, `x`, `y` and a
handful of styling flags. A renderer receiving `{"type": "gauge", "x": "kpi", "y":
["value"]}` has no idea what the gauge's range or bands are; a radar has no indicator
list; a scatter has no size or colour dimension; a heatmap has no matrix contract. The
renderer either guesses or degrades, and the agent has no place to say what it means.

Four related gaps block the surfaces users are asking for:

1. **Granularity.** Specialized objects (gauges, radar, scatter, heatmaps, treemaps,
   waterfalls) need per-type configuration and a per-type data shape. Today neither the
   wire nor any preparer knows those shapes, so the LLM must produce exactly the right
   DataFrame by luck, and every renderer re-implements the pivot logic.
2. **Vocabulary (revision 2).** The Parrot `Chart` and `KPICard` carry presentation
   *mechanics* on the wire: `palette` is a list of hex strings, `negativeColor` /
   `positiveColor` are hex, `KPICard.color` is a CSS colour, `layout: full|half` is a
   grid instruction, and the chart form is a closed `type` enum. Four renderers with
   four themes cannot honour hex colours consistently, an LLM should never be asked to
   pick them, and a `type` enum cannot express "these two series share one frame" or
   "this series is the story, that one is context". The viz-core draft states the
   alternative: the agent describes **what** to plot (rows, fields, scale types, marks,
   semantic colour roles, semantic formats, size intent) and each renderer decides
   **how** with its own library and theme. No colour, font, pixel or library option
   travels on the wire.
3. **Structure.** There is no graph, DAG or flow component in the Parrot catalog.
   Mermaid exists only as a vetted library in the legacy interactive-HTML lane
   (`parrot/models/interactive.py`). Agents that reason about workflows (the dev loop,
   `AgentsFlow` definitions, dependency graphs) cannot render them as A2UI.
4. **Liveness.** `Timeline` is a static list of `{timestamp, title, description}`. An
   operator watching a dev-loop run wants an animated timeline plus a graph whose nodes
   change state as the run progresses, and a click on a node that drills down into its
   dispatch, logs and artifacts, without an LLM turn per click. The dev loop already
   streams reduced `DevLoopSessionState` over a WebSocket, but nothing bridges that state
   into an A2UI surface.

Terminology carried forward from FEAT-527: templates are prompt specs, blocks are Parrot
models, themes are lane-neutral. Nothing here re-opens those decisions.

## Constraints & Requirements

- **Renderer-neutral wire.** Four renderers must render the new objects natively in the
  first release: navigator-frontend-next (Svelte 5), the bundled `ai-parrot-server/ui`
  canvas, the backend ECharts / interactive-HTML lane, and the static SSR-HTML / PDF lane.
  A vendor-specific option object cannot be the primary description.
- **What, never how (revision 2).** On every viz-core wire: no hex or named colours, no
  fonts, no pixel sizes, no library options. Colour is a semantic role (`categorical`
  with an optional fixed `slot` 1..8, `status` with `good|warning|serious|critical`,
  `sequential` / `diverging` driven by a row field for matrix marks, `neutral`). Formats
  are semantic (`currency|percent|compact|integer|date|month|year` plus a `unit`), never
  printf strings. Size is intent (`inline|tile|hero`), never pixels. Extension hints
  (`metadata.extensions.parrot_*`) are non-portable and only for tool-authored
  envelopes when a human asked for a library-specific override.
- **Grammar, not a type enum (revision 2).** A chart is a frame (`Chart`: one x axis with
  an explicit scale type `temporal|quantitative|ordinal|nominal`, one y axis, a
  coordinate system) with one or more `Series` children (a `field`, a `mark`, a colour
  role, an `emphasis`). Series are real child components so they can be added or
  replaced with `updateComponents`, or generated from the data model with a `ChildList`
  template. **One y axis per chart** — two measures of different magnitude are two
  charts or an indexed series; the revision-1 `secondaryY` is dropped.
- **Two authoring tiers on one wire.** The LLM authors a small intent-level spec through
  the existing validate-retry-degrade producer; deterministic code (tools, recipes, flow
  runners) authors full-detail specs. Same component, same schema, different depth.
- **Data contracts are declared, preparation is server-side.** Each form states the row
  shape it needs; a deterministic Python preparer validates or reshapes the data before
  the envelope is built. The renderer never transforms data (viz-core rule 3). The LLM
  names columns and roles only.
- **Third catalog, legacy untouched (revision 2).** viz-core ships under its own
  `catalogId`. The Parrot catalog `Chart`, `KPICard` and the FEAT-527 recipe emitters
  keep working unchanged for navigator-frontend-next's `AppChartConfig` lane; no
  deprecation in this round. Surfaces may mix catalogs per component (the A2UI v1.0
  `catalogId` resolution rule, already implemented by `resolve_catalog`).
- **Mermaid compatibility both ways.** The wire carries typed nodes and edges; a pure
  Python codec imports mermaid text into that shape and exports it back.
- **FEAT-470 invariants hold.** A2UI core imports nothing from `parrot.bots` or
  `parrot.clients`; `lower()` is mandatory for every composite; presentation semantics
  outside the schema live under `metadata.extensions.parrot_*`; the D10b origin gate
  (`ProducerOrigin.LLM` may not carry actions) is reused, not duplicated.
- **FEAT-473 schema parity by construction.** New vocabulary is Pydantic first and fed to
  `derive_schema`; no hand-maintained JSON Schema. The authored `viz-core.catalog.json`
  is the *design reference*; the shipped catalog JSON is exported from the Pydantic
  models and a drift test asserts the two agree on the properties they share.
- **Additive to FEAT-527.** Every envelope FEAT-527 emits stays valid; the new
  `Timeline` fields are optional.
- **No new frontend dependencies** in the bundled UI beyond `echarts` and `d3-*` already
  in `package.json`; static rendering runs no JavaScript (weasyprint constraint).

---

## Options Explored

### Option A: One catalog component per object type

Add `Gauge`, `RadarChart`, `ScatterChart`, `Heatmap`, `Treemap`, `Graph`, `WorkflowRun`
and so on as separate Parrot composites, each with its own `SCHEMA`, `INSTRUCTIONS` and
`lower()`.

✅ **Pros:**
- Strictest possible validation per type; no conditional schema.
- Each component's prompt instructions are short and focused.
- Renderers intercept by component name, as they do today for `Chart`/`DataTable`/`Map`.

❌ **Cons:**
- The Parrot catalog roughly doubles (10 → ~19 composites); every renderer's
  `supported_components` table and every degradation matrix grows with it.
- The LLM producer prompt grows with every new instruction block.
- Overlaps awkwardly with `Chart{type: "gauge"}`, which FEAT-527 already ships; two ways
  to say the same thing.
- The workflow surface becomes a monolithic component instead of a composition.
- Still carries hex colours and a `type` enum on the wire (the vocabulary gap stays).

📊 **Effort:** High

📦 **Libraries / Tools:** none beyond Option D's.

🔗 **Existing Code to Reuse:**
- `parrot/outputs/a2ui/catalog/__init__.py` — `register_component`
- `parrot/outputs/a2ui/catalog/parrot/chart.py` — pattern for a derived-schema composite

---

### Option B: Typed `spec` on `Chart` + `Graph` composite + `Timeline` v2 (revision-1 recommendation; charts part superseded by D)

`Chart` keeps its intent-level fields and gains an optional `spec` whose JSON Schema is a
`oneOf` keyed on `type`, derived from a Pydantic discriminated union of per-type spec
models (`GaugeSpec`, `RadarSpec`, `ScatterSpec`, `HeatmapSpec`, `TreemapSpec`,
`FunnelSpec`, `WaterfallSpec`, `CartesianSpec`). Each spec declares a `DataContract`; a
server-side preparer reshapes rows to it. Structure gets one new composite, `Graph`, with
typed nodes, edges, layout hints, bindable per-node state and a Python mermaid codec.
Time gets an additive `Timeline` v2 (lanes, spans, state, live playhead). The live
workflow surface is a **composition** (`Graph` + `Timeline` + detail card) fed by a
flow-event bridge that emits `updateDataModel`.

✅ **Pros:**
- Additive to FEAT-527; one interception point per renderer for charts.
- Schema parity by construction preserved (`derive_schema` over Pydantic models).
- Two authoring tiers fall out naturally: `spec` absent = intent tier, present = detail
  tier.
- Workflow surface reuses `Graph`/`Timeline` v2 for any `AgentsFlow`, not only the dev
  loop.

❌ **Cons:**
- `oneOf` conditional schema is harder for the LLM than flat props.
- Keeps the `type` enum as the primary axis, so it keeps `palette` hex and `layout:
  half` on the wire — the vocabulary gap (Problem 2) is not closed.
- A `CartesianSpec.secondaryY` invites dual-axis charts, the most common chart mistake.
- Static SVG rendering for seven chart families plus graph layout is real work in Python.
- Hand-written mermaid tokenizer is a maintenance surface.

📊 **Effort:** High (spread across three specs)

📦 **Libraries / Tools:** as Option D.

🔗 **Existing Code to Reuse:** as Option D, plus `parrot/models/outputs.py` for the
`StructuredChartConfig.spec` field (no longer needed).

**Status after revision 2:** the `Graph` and `Timeline` v2 parts of this option are
retained verbatim (see Feature Description, Sections 3 and 4). The `Chart.spec` union,
`DataContract` class attribute and `secondaryY` are superseded by Option D.

---

### Option C: Vendor passthrough

Carry an ECharts option object or a mermaid source string under `metadata.extensions`
and let capable renderers use it verbatim.

✅ **Pros:**
- Fastest route to full fidelity for the two renderers that speak ECharts or mermaid.
- Zero new vocabulary to teach.

❌ **Cons:**
- Not renderer-neutral: the Svelte, bundled UI and static lanes receive nothing they can
  validate or draw.
- Cannot be validated for LLM-origin envelopes; arbitrary option objects are an injection
  surface.
- Locks the wire to vendor versions.

📊 **Effort:** Low

📦 **Libraries / Tools:** none.

🔗 **Existing Code to Reuse:**
- `parrot/outputs/a2ui/models.py` — `Extensions` (`parrot_*` namespace)

---

### Option D: `viz-core` — a third A2UI catalog with a grammar of graphics (recommended for charts)

Ship the two artifacts as a real catalog: `catalogId`
`https://ai-parrot.dev/a2ui/catalogs/viz-core/1.0/catalog.json` (as authored; see Open
Questions on the domain), official `catalog.json` shape (`protocolVersion`, `catalogId`,
`instructions`, `components`, `functions`, `$defs.anyComponent`), every `$ref` into the
vendored `common_types.json` (`DynamicString`, `DynamicValue`, `DynamicNumber`,
`ChildList`, `Action` — all present). Components:

- **`Chart`** — the frame: `data` binding to an array of rows, `x{field, type, title?,
  format?, unit?, sort?}`, `y{title?, format?, unit?, zeroBased}`, `series` (a
  `ChildList`: static ids or a `{componentId, path}` template), `seriesBy` for long
  data, `orientation`, `stack: none|normal|percent`, `legend: auto|hidden`, `size:
  inline|tile|hero`, `accessibleDescription`, `weight`. **Revision-2 additions**:
  `coordinates: cartesian|polar` (default `cartesian`), and the standard component-level
  `action` in place of the draft's `selectAction` (renderer adds `{seriesId, x, y}` to
  the context).
- **`Series`** — one layer of marks: `field`, `label?`, `mark: line|bar|area|point|arc|
  rect`, `color{role, slot?, value?, field?}`, `emphasis: normal|primary|muted`,
  `labels: auto|ends|all|none`.
- **`Stat`** — one headline number: `label`, `value`, `format`, `unit`,
  `delta{value, format, sentiment, reference}`, `trend{data, x?, field}` sparkline.
  **Revision-2 addition**: `gauge{min, max, bands[{from, to, status, label?}], target?}`
  — a single ratio against a limit (the dataviz "meter" form), so `Chart{type:
  "gauge"}` has a semantic home.
- **`Treemap`** (revision-2 addition) — hierarchical part-to-whole: `data`,
  `labelField`, `valueField`, `parentField?`, `depth?`, `color{role: categorical|
  sequential, field?}`, `size`, `accessibleDescription`, `action`.
- **`Graph`** — moved here from the Parrot catalog (see Section 3 below).

The five FEAT-527 complex forms map onto that grammar (the **hybrid** decision):

| FEAT-527 `Chart.type` | viz-core representation | Preparation |
|---|---|---|
| `radar` | `Chart{coordinates: polar, x{type: nominal}}` + `line`/`area` `Series` (one per series, or `seriesBy`) | long → wide if `seriesBy`; indicator max from column max |
| `funnel` | `Chart{orientation: horizontal, x{type: nominal, sort: byValue}}` + one `bar` `Series` | sort descending; fold beyond 8 steps |
| `waterfall` | `Chart` + `bar` `Series{color{role: status, field: "sign"}}` over prepared rows `{step, delta, running, sign}` | running totals computed server-side; totals rows flagged |
| `gauge` | `Stat{gauge{min, max, bands, target}}` | none |
| `treemap` | `Treemap` | `parentField` cycle check; depth cut |
| `heatmap` | `Chart{x{type: ordinal}}` + `rect` `Series{color{role: sequential\|diverging, field}}` | dense `{x, y, value}` with `null` fill |
| `pie` / `donut` | `Chart` + `arc` `Series` (≤ 5 categories, else `bar` with `stack: percent`) | fold to "Other" |

✅ **Pros:**
- Closes Problem 2: nothing on the wire is a colour, a font, a pixel or a library option;
  every renderer paints with its own theme, and the dataviz rules (one axis, fixed
  categorical slots, status colours reserved, ≤ 8 series) are enforced by schema and
  instructions rather than by hoping.
- Series as child components give `updateComponents` granularity and `ChildList`
  templates for free (official v1.0 mechanisms, already baked by `bake_envelope`).
- Explicit x scale type ends the "is this a date?" guessing in four renderers.
- Multi-catalog surfaces are already supported by `resolve_catalog` /
  `_component_exists`; the legacy Parrot `Chart` stays for navigator-frontend-next and
  FEAT-527 recipes, so nothing breaks.
- Gauge, radar, funnel, waterfall and treemap each get an honest representation
  instead of a `type` string with no semantics.

❌ **Cons:**
- The catalog registry (`_CATALOG`) is keyed by bare name today; a second `Chart` cannot
  register until the registry is keyed by `(catalogId, name)`. Renderer interception
  tables and `supported_components` are bare-name sets and must carry the catalog id for
  viz-core entries.
- Two `Chart`s exist for a while (Parrot's type-based one and viz-core's frame). The
  producer prompt must scope instructions to the surface's catalogs so the LLM never
  sees both.
- A frame + children is more envelope surface than one flat `Chart` for the LLM to
  author correctly; mitigated by `seriesBy` (one `Series`) and by the intent tier.
- `polar` coordinates and `Stat.gauge` are additions to the authored draft and need a
  drift test against it.
- Static SVG for six marks × two coordinate systems plus `Treemap` and the graph is real
  Python work (as in Option B).

📊 **Effort:** High (spread across three specs; the catalog shell is small)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (present) | `Chart`/`Series`/`Stat`/`Treemap`/`Graph` spec models | `derive_schema` → wire schema |
| `jsonschema` (present, FEAT-470 G8) | validates the viz-core `catalog.json` against the vendored `catalog_definition.json`; drift test vs the authored draft | already a hard core dep |
| `pandas` (present, core hard dep) | preparers (long → wide, running totals, dense matrix) | imported lazily inside preparer functions |
| `echarts` (present in bundled UI + satellite) | line/bar/scatter/pie/heatmap/radar/treemap/graph series | no new dep |
| `weasyprint` (present, PDF) | rasterizes SSR HTML with inline SVG | no JS |
| none | mermaid codec, layered graph layout, static SVG marks | hand-written, pure Python |

🔗 **Existing Code to Reuse:**
- `parrot/outputs/a2ui/catalog/__init__.py` — `register_component(catalog_id=...)`,
  `resolve_catalog`, `_component_exists` (third-catalog branch already exists)
- `parrot/outputs/a2ui/catalog/export.py` — `export_catalog_definition(catalog_id=...)`
- `parrot/outputs/a2ui/catalog/parrot/_derive.py` — `derive_schema`
- `parrot/outputs/a2ui/catalog/base.py` — `ProducerOrigin`, D10b gate
- `parrot/outputs/a2ui/models.py` — `ChildTemplate`, `UpdateDataModel`, `Extensions`
- `parrot/outputs/a2ui/baking.py` — `_expand_template` (Series from a data-model list)
- `parrot/outputs/a2ui/renderers/__init__.py` — `RendererCapabilities.supported_catalog_ids`
- `parrot/outputs/a2ui/adapters/structured.py`, `adapters/infographic.py` — the two
  call sites that will *optionally* emit viz-core instead of Parrot `Chart`
- `parrot/bots/flows/flow/definition.py` — `NodeDefinition`, `EdgeDefinition`, `FlowDefinition`
- `parrot/bots/flows/flow/flow.py` — `add_node_event_listener`, `_notify_node_event`
- `parrot/flows/dev_loop/session_state.py` — `DevLoopSessionState`, `NodeState`, `NodeStatus`
- `parrot/flows/dev_loop/streaming.py` — `FlowStreamMultiplexer` (state replay semantics)
- `ai-parrot-server/.../handlers/a2ui.py` — `A2UIHandler._get_stream` (SSE channel)
- `ai-parrot-visualizations/.../a2ui_renderers/echarts.py` — `_SERIES_TYPE`, `_ROW_NATIVE_TYPES`, `_build_option`
- `ai-parrot-visualizations/.../a2ui_renderers/pdf.py` — `_chart_svg` (to be replaced)
- `ai-parrot-visualizations/.../formats/assets/design_system` — status/accent tokens
  that the semantic colour roles resolve to

---

## Recommendation

**Option D for charts, Option B's `Graph` and `Timeline` v2 retained with `Graph` moved
under viz-core, plus a bounded, tool-only version of Option C as a hint.**

Option D is the only option that closes all four gaps. It satisfies the four-renderer
constraint *better* than B because nothing on the wire depends on a renderer's theme,
and it keeps the two authoring tiers on one wire (`seriesBy` + one `Series` is the
intent tier; explicit `Series` children with slots and emphasis is the detail tier). It
reuses FEAT-473's schema derivation, FEAT-470's catalog resolution rule and extension
namespace, and FEAT-469's runtime and SSE stream, so most of the new surface is
vocabulary, a small registry change, and adapters rather than machinery.

`Graph` belongs in viz-core because it is a visualization and the catalog is the home
for lane-neutral visualization vocabulary; splitting charts and graphs across two
catalogs would leave viz-core without its one structural form. `Graph` keeps
`layout.positions` on the wire: a layout is **server-side preparation** (the same rule
that says rows are prepared before binding), not styling — every lane draws the same
picture, and the bundled UI needs no JS layered-layout library.

The vendor hint is kept because deterministic tools sometimes have a tuned ECharts option
or an existing mermaid diagram and should not have to lose fidelity to fit the typed
spec. It is constrained so it can never become the primary description: `TOOL` origin
only, typed component always mandatory alongside it, and every use recorded on the
artifact.

Option A is rejected for catalog growth and the `Chart{type}` overlap. Option B's
`spec` union is rejected because it keeps hex colours, a `type` enum and a second y axis
on the wire. Option C alone is rejected for renderer neutrality and validation.

---

## Feature Description

### User-Facing Behavior

- An agent asked for "a gauge of on-time delivery against the 95% target with red /
  amber / green bands" produces a viz-core `Stat` with `gauge{min: 0, max: 100, bands:
  [{to: 80, status: critical}, {to: 95, status: warning}, {to: 100, status: good}],
  target: 95}` that every renderer draws as a meter with those bands in its own theme,
  never a one-bar chart or a text summary.
- An agent asked for "monthly sales by product line" produces a viz-core `Chart` with
  `x{field: month, type: temporal}`, `y{format: currency, unit: EUR}` and two `line`
  `Series`, one marked `emphasis: primary`. The same envelope renders in
  navigator-frontend-next, the bundled canvas, the ECharts lane and a PDF with each
  lane's own palette, and the legend and direct labels follow the dataviz rules.
- An agent asked to "show the dev-loop workflow" returns a viz-core `Graph` drawn as a
  flowchart. The same graph can be exported as mermaid text for a README, and a mermaid
  diagram pasted by a user can be imported into a surface.
- An operator opens a running dev-loop session and sees a graph whose nodes change
  colour as they start, complete or fail, a swimlane timeline with a moving playhead, and
  a detail panel that fills in when a node is clicked. No page reload, no LLM turn per
  click.
- Consumers that ignore viz-core components see today's output unchanged; the Parrot
  `Chart` lane (FEAT-527 recipes, navigator-frontend-next's `AppChartConfig`) is not
  touched. Static PDFs show a real meter, radar or flowchart instead of a data summary.

### Internal Behavior

**Wire — the viz-core catalog (Section 1).**
- New core package `parrot/outputs/a2ui/catalog/viz_core/`: `__init__.py`
  (`VIZ_CORE_CATALOG_ID`, `VIZ_CORE_INSTRUCTIONS` — the nine guideline rules from the
  draft, registration imports), `chart.py`, `series.py`, `stat.py`, `treemap.py`,
  `graph.py`, `spec/catalog.json` (the authored draft, kept as the design reference and
  drift-tested against the exported document).
- **Catalog shell** (lands with `a2ui-graph-component`): the registry `_CATALOG` is
  keyed by `(catalog_id, name)`; `get_component(name, catalog_id=None)` resolves a bare
  name when it is unique across catalogs and raises when ambiguous (all seven existing
  bare-name call sites keep working, since no name is duplicated until viz-core `Chart`
  lands); `_component_exists` uses the keyed lookup; `list_components(catalog_id=None)`
  and `catalog_instructions(catalog_ids=None)` filter, so the LLM producer only sees the
  instructions of the catalogs the surface uses; `export_catalog_definition(catalog_id=
  VIZ_CORE_CATALOG_ID)` emits the viz-core document (valid against the vendored
  `catalog_definition.json`); `RendererCapabilities.supported_catalog_ids` gains the
  viz-core id on lanes that draw it natively; renderer interception tables carry
  `(catalogId, name)` for viz-core entries; the bundled UI dispatch reads `catalogId`.
- Every viz-core component is Pydantic-first (`derive_schema`), registered with
  `register_component(name, catalog_id=VIZ_CORE_CATALOG_ID)`, has a mandatory
  `lower()` to Basic primitives whose first line is the `accessibleDescription` (falling
  back to a generated one-line summary), and declares the standard component-level
  `action` in its schema (`$ref common_types Action`) so the existing D10b gate covers
  it — the draft's `selectAction` is dropped.
- `Chart.series` is a `ChildList`; `Series` components are resolved by id from the flat
  component list (or expanded from a `{componentId, path}` template by the bake pass).
  `seriesBy` requires exactly one `Series`. `coordinates: polar` requires `x.type` in
  `{nominal, ordinal}`. `stack != none` requires stackable marks only. `> 8` `Series`
  is a validation error (fold or facet first).
- Vendor hint: `metadata.extensions.parrot_vendor = {echarts?: dict, mermaid?: str}`.
  `validate_envelope(origin=LLM)` rejects it (extends the D10b gate). Renderers that use
  it set `RenderedArtifact.metadata["hintUsed"] = [component ids]`. Owned by
  `a2ui-viz-core-charts`.

**Data preparation (Section 2).**
- New core package `parrot/outputs/a2ui/prepare/`: one preparer per form
  (`prepare_wide(rows, x, fields)`, `prepare_long(rows, x, series_by, field)`,
  `prepare_waterfall(rows, step, delta, totals)`, `prepare_matrix(rows, x, y, value)`,
  `prepare_hierarchy(rows, label, value, parent)`), `errors.py` (`DataContractError`
  subclassing `CatalogValidationError` so the producer's retry loop already handles it),
  and a `PreparationReport{rowsIn, rowsOut, aggregation, dropped, warnings}` attached
  under `metadata.extensions.parrot_preparation`.
- Call sites: `chart_to_surface()` and `infographic_response_to_envelope()` gain an
  opt-in `catalog="viz-core"` mode that emits viz-core `Chart`/`Series`/`Stat` instead of
  the Parrot `Chart`/`KPICard`; the default stays the Parrot catalog in this round. Both
  deterministic; the LLM never calls the preparer.
- Pandas imported lazily inside preparer functions; accepts DataFrame or list of dicts.

**`Graph` composite and mermaid codec (Section 3) — under viz-core.**
- `catalog/viz_core/graph.py`, registered `Graph` with `catalog_id=VIZ_CORE_CATALOG_ID`.
  Schema: `kind: flowchart|state|sequence|dag`, `direction: TB|LR|BT|RL`, `nodes[{id,
  label, shape?: rect|rounded|diamond|circle|hexagon|subroutine, group?, state?:
  pending|running|completed|failed|skipped|waiting, icon?, meta?}]`, `edges[{from, to,
  label?, kind?: solid|dashed|thick, condition?}]`, `groups[{id, label, nodes[]}]`,
  `layout{engine: layered|force|manual, rankSep?, nodeSep?, positions?}`,
  `selection{selectable, selected?}`, `data` (binding to an object keyed by node id
  overlaying `state`/`meta`/`label`), plus the viz-core common props `size`,
  `accessibleDescription`, `action` (TOOL origin only, existing gate; renderer adds
  `context.nodeId`/`nodeLabel`). Node `state` stays a domain enum; the renderer contract
  maps it to the semantic status roles: `completed → good`, `waiting → warning`,
  `failed → critical`, `running → primary emphasis`, `pending`/`skipped → neutral`.
- `layout.positions` stays on the wire, filled by the builder from the pure-Python
  layered layout in core (`catalog/viz_core/graph/layout.py` or the FEAT-529 spec's
  `parrot/outputs/a2ui/graph/`): a layout is preparation, not styling.
- `build_graph(...)` in `builders.py`; `adapters/flow.py::flow_definition_to_graph
  (Mapping) -> GraphSpec` (node `type` → shape; `condition`/`predicate` → edge label;
  fan-out `to: list` → one edge each). Pure; accepts the `model_dump(by_alias=True)`
  mapping so `adapters/` never imports `parrot.bots` (G8 rule untouched).
- `graph/mermaid.py`: `to_mermaid(spec) -> str`, `from_mermaid(text) -> GraphSpec`.
  Dialects: `flowchart` (incl. `subgraph`), `stateDiagram-v2`, `sequenceDiagram`.
  Hand-written tokenizer; `MermaidCodecError(line_no, line, reason)` subclassing
  `CatalogValidationError`. Round-trip asserted on every golden.
- Lowering: `Card{Column[Text accessibleDescription (parrot_role: description), Text
  title, Text "A → B (label)" per edge (parrot_role: edge), Text mermaid source
  (parrot_role: graph-source)]}`, `parrot_variant: graph`.
- Static: positions → SVG with shapes, edge paths, labels, status colours from
  `DesignSystem` tokens. Force layout degrades to layered with a `degraded` record.

**`Timeline` v2 and live workflow surface (Section 4) — unchanged from revision 1.**
- `Timeline` additive fields: `mode: list|gantt|live` (default `list`), `lanes[{id,
  label}]`, events gain `id`, `lane`, `start`, `end`, `state`, `progress`, `parent`,
  `meta`; `range{start, end?}` (open end = now); `playhead` (`DynamicString` binding);
  `data` binding overlaying per-event fields; `action` (TOOL origin only). Lowering
  degrades `gantt`/`live` to the row list with `state` as a badge. Whether `Timeline` v2
  moves under viz-core is an open question for the third spec.
- `parrot/outputs/a2ui/workflow.py::build_workflow_surface(definition, state=None) ->
  CreateSurface` emits `Column[Graph, Timeline(mode=live), InfoCard(detail)]`; graph and
  timeline bind `data` to `/nodes`, the card binds to `/selected`.
- `parrot/outputs/a2ui/workflow.py::FlowSurfaceBridge`: `translate(node_id, status,
  info) -> list[UpdateDataModel]` (pure), `attach(flow: AgentsFlow)` via
  `add_node_event_listener`, and `from_session_state(DevLoopSessionState) ->
  UpdateDataModel` (snapshot on `/`). Emits on the FEAT-469 SSE stream
  (`A2UIHandler._get_stream`), which gains a second source alongside pending
  `callRendererFunction`. Reconnect replays the snapshot. Failures are logged warnings,
  never raised into the flow (same policy as `_notify_node_event`).
- Drill-down: node click → `action{name: "graph.select", context: {nodeId}}` → runtime
  → registered agent function `describe_flow_node(run_id, node_id)` → `updateDataModel
  {path: "/selected", value}` (+ `updateComponents` for rich detail). No LLM turn.
- Animation is renderer-side and declared: renderers with `supports_updates=True`
  animate state transitions with a documented default duration; static renderers show
  the snapshot.

**Renderer matrix (Section 5).**

| Renderer | viz-core `Chart`/`Series`/`Stat`/`Treemap` | viz-core `Graph` | Timeline v2 | Updates / actions |
|---|---|---|---|---|
| navigator-frontend-next (Svelte 5) | all marks native (contract doc) | layered + force | list/gantt/live | SSE updates, actions |
| bundled UI `canvas/a2ui` | all marks native (echarts), dispatch by `catalogId` | positions → echarts `graph` | list/gantt/live | SSE updates, actions |
| ECharts (satellite) | all marks native (`_build_option` per mark/coordinates) | ECharts `graph` series | gantt via custom series | none (static HTML) |
| interactive-html | Chart.js cartesian marks; `polar`/`Treemap`/`Stat.gauge` degrade (recorded) | Python layered SVG | list/gantt static | none in v1 |
| SSR-HTML / PDF | Python SVG per mark × coordinates + `Treemap` + meter (replaces `_chart_svg`) | Python layered SVG | gantt SVG | none |
| Adaptive Cards / Folium | lowering only (`accessibleDescription` + table) | lowering only | lowering only | as today |
| Legacy Parrot `Chart`/`KPICard` lane | **unchanged** on every renderer | — | — | — |

### Edge Cases & Error Handling

- A viz-core component in a surface whose renderer lacks the viz-core id in
  `supported_catalog_ids` → lowered fallback (`accessibleDescription` + table/edge list)
  with a `degraded[]` record naming the catalog; never a throw.
- Two components named `Chart` in one envelope with different `catalogId`s → each
  validates against its own catalog; a bare `Chart` in a surface whose default catalog
  is Parrot's resolves to the Parrot `Chart` (resolution rule unchanged).
- `seriesBy` set with more than one `Series` → `CatalogValidationError`; `coordinates:
  polar` with `x.type: temporal|quantitative` → `CatalogValidationError`; more than 8
  `Series` → `CatalogValidationError` ("fold to Other or facet"); `stack` with a
  non-stackable mark → `CatalogValidationError`. LLM lane retries once then degrades,
  TOOL lane raises.
- `Series.color.role: status` without `value`, or `sequential|diverging` without
  `field` → `CatalogValidationError`; `slot` collision between two `Series` → error.
- `Stat.gauge` bands that overlap, leave a gap, or exceed `[min, max]` → error; `target`
  outside `[min, max]` → error.
- `Treemap` with a `parentField` cycle or an orphan parent → `DataContractError`
  naming the row.
- `DataContractError` (missing field, wrong cardinality, non-numeric value column) →
  message carries field, expected shape and a repair hint; producer feeds it to the
  repair prompt; never renders a wrong chart silently.
- Heatmap with sparse cells → dense fill with `null`; renderer paints missing as empty.
- Preparer receives more rows than the form allows and no aggregation declared →
  `DataContractError` (no implicit aggregation).
- Vendor hint present on an `LLM`-origin envelope → rejected with the existing
  `UNALLOWED_*` code family; on `TOOL` origin without a typed component → rejected (hint
  never stands alone).
- `Graph` with an edge to an unknown node, a cycle in `kind: dag`, or `manual` layout
  without `positions` → validation error at build time.
- `from_mermaid` meets an unsupported construct (class diagrams, `click` directives,
  styling blocks) → `MermaidCodecError` naming the line; nothing is silently dropped.
- `to_mermaid` on a node label containing mermaid-reserved characters → quoted label.
- `Graph.data` binding resolves to an object missing some node ids → those nodes keep
  their static `state`.
- Static layout for graphs above a size threshold (proposed 200 nodes) → truncate with a
  recorded `degraded` entry rather than time out.
- Bridge: `updateDataModel` for a node id not in the surface is ignored by the renderer
  (v1.0 semantics); the bridge logs at debug. SSE client disconnect → bridge drops that
  subscriber; the flow run is unaffected.
- Drill-down on a node with no `NodeState` yet → `/selected` gets `{nodeId, state:
  "pending"}` and the detail card shows "not started".

---

## Capabilities

### New Capabilities
- `a2ui-graph-component` (**FEAT-529**, spec exists — re-run as v0.2): the viz-core
  **catalog shell** (`VIZ_CORE_CATALOG_ID`, `(catalog_id, name)`-keyed registry,
  scoped `catalog_instructions`, exporter, `supported_catalog_ids`, renderer dispatch by
  catalog id, bundled-UI dispatch by `catalogId`) **plus** the `Graph` composite under
  viz-core, `build_graph`, `flow_definition_to_graph`, mermaid codec (flowchart,
  stateDiagram-v2, sequenceDiagram), lowering, pure-Python layered layout → positions
  → SVG, ECharts graph series, bundled UI + Svelte contract doc.
- `a2ui-viz-core-charts` (renamed from `a2ui-typed-chart-specs`; spec not yet written):
  viz-core `Chart`/`Series`/`Stat`/`Treemap` models and schemas, `coordinates: polar`,
  `Stat.gauge`, the complex-form mapping table, `parrot/outputs/a2ui/prepare/`
  preparers, opt-in viz-core emission in both adapters, tool-only `parrot_vendor` hint +
  gate, ECharts native series per mark, Python static SVG per mark/coordinates, bundled
  UI + Svelte contract doc, drift test against `artifacts/a2ui/viz-core.catalog.json`.
- `a2ui-live-workflow-surface` (spec not yet written): `Timeline` v2 fields and
  lowering, `build_workflow_surface`, `FlowSurfaceBridge`, SSE second source in
  `A2UIHandler`, `describe_flow_node` agent function, dev-loop runner wiring, renderer
  animation contract, gantt SVG.

Recommended order (revision 2): **graph → charts → live surface**. The graph spec lands
the shell so `Graph` can proceed now; the charts spec adds `Chart`/`Series`/`Stat`/
`Treemap` onto the shell; the live surface depends on `Graph`.

### Modified Capabilities
- `infographic-a2ui-migration` (FEAT-527): `ChartType` widening and `CHART_TYPE_MAP`
  stay as the legacy lane; the adapter gains an opt-in viz-core emission mode. The
  "Chart.js / bundled UI degrade with a recorded entry" rule for gauge/treemap/waterfall
  in the bundled UI is replaced (native via echarts) **only for viz-core envelopes**;
  the legacy `Chart` lane keeps its current behaviour.
- `a2ui-v1-structured-outputs` (FEAT-473): `chart_to_surface` gains the opt-in viz-core
  mode and calls the preparer there; `StructuredChartConfig` is **not** changed (no
  `spec` field).
- `a2ui-agent-functions` (FEAT-469): `A2UIHandler._get_stream` gains a second event
  source (bridge updates); a new registered agent function `describe_flow_node`.
- `a2ui-v1-dialect` (FEAT-470): third catalog id; registry keyed by `(catalog_id,
  name)`; `catalog_instructions` scoped by catalog; `Timeline` schema widened
  (additive); D10b gate extended to `parrot_vendor`; `parrot_role` vocabulary gains
  `description`, `edge`, `edge-list`, `graph-source`, `lane`, `span`, `playhead`.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/outputs/a2ui/catalog/__init__.py` | modifies | `_CATALOG` keyed by `(catalog_id, name)`; `get_component(name, catalog_id=None)`; `list_components`/`catalog_instructions` scoped; `_component_exists` keyed; `parrot_vendor` gate (charts spec) |
| `parrot/outputs/a2ui/catalog/viz_core/` | creates | `VIZ_CORE_CATALOG_ID`, instructions, `graph.py` (FEAT-529), `chart.py`/`series.py`/`stat.py`/`treemap.py` (charts spec), `spec/catalog.json` (authored draft) |
| `parrot/outputs/a2ui/catalog/export.py` | uses / extends | `export_catalog_definition(catalog_id=VIZ_CORE_CATALOG_ID)`; `write_catalog_definition` for the viz-core document; `describe_flow_node` function later |
| `parrot/outputs/a2ui/renderers/__init__.py` | extends | `supported_catalog_ids` documented to include viz-core on native lanes |
| `parrot/outputs/a2ui/producer.py` | modifies | passes the surface's catalog ids to `catalog_instructions` |
| `parrot/outputs/a2ui/catalog/parrot/chart.py`, `kpicard.py` | none | legacy lane untouched in this round |
| `parrot/outputs/a2ui/catalog/parrot/timeline.py` | extends (live spec) | v2 fields, `gantt`/`live` lowering |
| `parrot/outputs/a2ui/graph/` (or `catalog/viz_core/graph/`) | creates (FEAT-529) | `models.py`, `mermaid.py`, `layout.py` |
| `parrot/outputs/a2ui/prepare/` | creates (charts spec) | preparers, errors, report |
| `parrot/outputs/a2ui/workflow.py` | creates (live spec) | `build_workflow_surface`, `FlowSurfaceBridge` |
| `parrot/outputs/a2ui/adapters/structured.py`, `adapters/infographic.py` | modifies (charts spec) | opt-in viz-core emission + preparer call |
| `parrot/outputs/a2ui/adapters/flow.py` | creates (FEAT-529) | `flow_definition_to_graph` |
| `parrot/outputs/a2ui/builders.py` | extends | `build_graph` (FEAT-529); `build_viz_chart`, `build_stat`, `build_treemap` (charts spec); `build_timeline`, `build_update_data_model` (live spec) |
| `parrot/outputs/a2ui/catalog/basic/spec/` | none | vendored official schemas untouched |
| `ai-parrot-server/.../handlers/a2ui.py` | extends (live spec) | SSE stream second source |
| `parrot/flows/dev_loop/runner.py` | extends (live spec) | attaches `FlowSurfaceBridge`; registers `describe_flow_node` |
| `ai-parrot-visualizations/.../a2ui_renderers/echarts.py` | extends | `supported_catalog_ids` + `Graph` series (FEAT-529); per-mark/coordinates option building (charts spec); gantt (live spec) |
| `ai-parrot-visualizations/.../a2ui_renderers/ssr_html.py`, `pdf.py` | modifies | intercept viz-core `Graph` → SVG (FEAT-529); marks/meter/treemap SVG replacing `_chart_svg` (charts spec); `Timeline` gantt (live spec) |
| `ai-parrot-visualizations/.../a2ui_renderers/_graph_svg.py`, `_marks_svg.py` | creates | static SVG |
| `ai-parrot-visualizations/.../a2ui_renderers/interactive_html.py` | extends | `_INTERCEPTED` keyed by `(catalogId, name)` for viz-core; `Graph` embed (FEAT-529); marks via Chart.js (charts spec) |
| `ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/*` | extends | dispatch on `catalogId` (FEAT-529); `A2UIGraph.svelte`; viz-core chart adapter (charts spec); `Timeline` v2 + SSE (live spec) |
| `docs/frontend/agentdashboard-a2ui-reference.md`, `docs/outputs/a2ui-v1.md` | docs | "three catalogs" section; viz-core contract; `Graph`; later `Chart`/`Series`/`Stat`/`Treemap`, `Timeline` v2, `parrot_vendor`, bridge stream |
| Golden fixtures + conformance suite | extends | per component goldens; round-trip goldens; viz-core `catalog.json` export validates against vendored `catalog_definition.json`; drift test vs the authored draft |

No breaking changes on the wire. New hard dependencies: none. Optional: none.

---

## Code Context

### User-Provided Code

The two artifacts are the user-provided design input for revision 2 and are kept
verbatim at `artifacts/a2ui/viz-core.catalog.json` and
`artifacts/a2ui/viz-core.example.jsonl`. Key excerpts (draft 0.1):

```jsonc
// artifacts/a2ui/viz-core.catalog.json (top level + component names)
{
  "$id": "https://ai-parrot.dev/a2ui/catalogs/viz-core/1.0/catalog.json",
  "protocolVersion": "1.0",
  "catalogId": "https://ai-parrot.dev/a2ui/catalogs/viz-core/1.0/catalog.json",
  "instructions": "## Viz Core Guidelines\n\n1. Pick the form by the data's job ... 9. Do not set metadata.extensions render hints unless a human asked ...",
  "components": { "Chart": {...}, "Series": {...}, "Stat": {...} },
  "functions": {},
  "$defs": { "anyComponent": { "oneOf": [...], "discriminator": { "propertyName": "component" } } }
}
// Chart.required = ["component", "data", "x", "series"]; Series.required = ["component", "field", "mark"];
// Stat.required = ["component", "label", "value"]. Series.mark enum: line|bar|area|point|arc|rect.
// Series.color: {role: categorical|status|sequential|diverging|neutral, slot 1..8, value good|warning|serious|critical, field}.
// Chart.size: inline|tile|hero. Chart.selectAction: $ref common_types Action (→ replaced by the standard `action`, revision 2).
```

```jsonc
// artifacts/a2ui/viz-core.example.jsonl — line 1 is a createSurface whose surface catalogId is the Basic
// catalog and whose Stat/Chart/Series components each carry the viz-core catalogId; line 2 is an
// updateDataModel appending a row at /sales/rows/3. Parrot builders will set the surface default to
// the Parrot catalog and the per-component catalogId to viz-core.
```

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/_derive.py:88
def derive_schema(
    model: type[BaseModel],
    *,
    binding_fields: Sequence[str],
    required: Sequence[str] = (),
) -> dict[str, Any]: ...

# From packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py:95, :107, :181, :190, :219, :233, :266
_CATALOG: dict[str, RegisteredComponent] = {}          # keyed by BARE NAME today (revision-2 change target)
def register_component(name: str, *, requires_actions: bool = False, catalog_id: str = DEFAULT_CATALOG_ID,
                       is_primitive: bool = False, allowed_parents: list[str] | None = None,
                       allowed_children: list[str] | None = None, tool_only: bool = False) -> Callable[[type], type]
def get_component(name: str) -> RegisteredComponent            # 7 bare-name call sites outside this module (see below)
def list_components() -> list[ComponentDefinition]
def catalog_instructions() -> str                              # aggregates EVERY registered component's instructions, unscoped
def resolve_catalog(component_catalog_id: str | None, surface_catalog_id: str | None) -> str   # component wins, else surface, else CATALOG_UNRESOLVED
def _component_exists(name: str, resolved_catalog_id: str) -> bool   # :286 basic, :288 parrot (+basic), :293 ANY OTHER catalog id via registry entry.catalog_id
# :498-502 — the LLM-origin action gate: `entry_for_gate = _CATALOG.get(comp.component)`;
#   `is_action_bearing = comp.action is not None or entry.definition.requires_actions` — checks ONLY the
#   component-level `action` prop (a catalog-declared `selectAction` prop would bypass it).

# From packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py:53, :89, :101, :224
DEFAULT_CATALOG_ID = "https://parrot.dev/catalogs/v1"
class ProducerOrigin(str, Enum): ...   # LLM / TOOL; drives the D10b action gate
class BasicNode(BaseModel): ...        # lower() output tree; to_components() flattens (:164)
class ComponentDefinition(BaseModel): name; catalog_id; schema_; instructions; requires_actions; is_primitive; allowed_parents; allowed_children; tool_only

# From packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/__init__.py:44, :90, :205
BASIC_CATALOG_ID = "https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json"
def load_spec(name: SpecName) -> dict
def basic_components() -> list

# From packages/ai-parrot/src/parrot/outputs/a2ui/catalog/export.py:215
def export_catalog_definition(*, catalog_id: str = DEFAULT_CATALOG_ID, include_basic: bool = True,
                              executor: FunctionExecutor | None = None) -> dict[str, Any]
# emits {"$schema", "protocolVersion": "1.0", "catalogId", "instructions": catalog_instructions(), "components", "functions"}
# — filters components by `definition.catalog_id == catalog_id`, so a viz-core export already works once
# components are registered under that id; `instructions` is currently UNscoped (see catalog_instructions).

# From packages/ai-parrot/src/parrot/outputs/a2ui/models.py:212, :250, :341, :364, :400, :431, :490
class ChildTemplate(BaseModel): component_id: str = Field(alias="componentId"); path: str
class Action(BaseModel): event | function_call
class Extensions(RootModel[dict[str, Any]]): ...   # parrot_* keys; official-prefix keys rejected
class ComponentMetadata(BaseModel): extensions: Extensions | None = None
class Component(BaseModel): id; component; catalog_id (alias catalogId, :431); child; children: ChildList | None (:433); action: Action | None; metadata; extra="allow"
class UpdateDataModel(A2UIMessageBase): surface_id; path: str | None; value: Any

# From packages/ai-parrot/src/parrot/outputs/a2ui/baking.py:307, :356
def _expand_template(template: ChildTemplate, *, by_id, data_model) -> ...   # ChildList template → clones, scope_path per item
def bake_envelope(envelope: CreateSurface) -> list[dict[str, Any]]

# From packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py:51, :74
class RendererCapabilities(BaseModel):
    interactive: bool; supports_actions: bool; supports_updates: bool; output: str
    supported_catalog_ids: list[str] = Field(default_factory=lambda: [BASIC_CATALOG_ID, DEFAULT_CATALOG_ID])
    supported_components: set[str] = Field(default_factory=set)   # BARE names

# From packages/ai-parrot/src/parrot/outputs/a2ui/renderers/degrade.py:24, :46
def degrade(node: BasicNode, reason: str) -> BasicNode
def degradation_record(node: BasicNode, reason: str) -> dict[str, Any]

# From packages/ai-parrot/src/parrot/models/outputs.py:322
class StructuredChartConfig(BaseModel):   # legacy Parrot Chart vocabulary — UNCHANGED by this brainstorm
    type: ChartType; x: str; y: List[str]; stacked; trendline; split_series; show_legend;
    x_axis_mode; palette: Optional[List[str]] (hex); color_by_sign; negative_color (hex); positive_color;
    map_name; title; description; data: List[dict] (input-only); data_variable; layout ("full"|"half")

# From packages/ai-parrot/src/parrot/models/infographic.py:103
class ChartType(str, Enum): BAR, LINE, PIE, DONUT, AREA, SCATTER, RADAR, HEATMAP, TREEMAP, FUNNEL, GAUGE, WATERFALL

# From packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py:293 and adapters/structured.py:202
#   both emit the PARROT `Chart` (`_descriptor("Chart", properties)` / `build_surface("Chart", ...)`) — the two
#   opt-in call sites for viz-core emission in the charts spec.

# From packages/ai-parrot/src/parrot/bots/flows/flow/definition.py:155, :246, :377
class NodeDefinition(BaseModel):  id: str; type: str; label: Optional[str]; agent_ref; instruction; max_retries ...
class EdgeDefinition(BaseModel):  id; from_ (alias "from"); to: Union[str, List[str]];
                                  condition: Literal["always","on_success","on_error","on_timeout","on_condition"]; predicate
class FlowDefinition(BaseModel): ...

# From packages/ai-parrot/src/parrot/bots/flows/flow/flow.py:470, :483
def add_node_event_listener(self, callback: Callable[[str, str, Dict[str, Any]], Any]) -> None
def _notify_node_event(self, event: str, node_id: str, info: Dict[str, Any]) -> None   # fire-and-forget, warns on exception

# From packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py:161, :165, :243, :330
NodeStatus = Literal["idle", "running", "completed", "failed", "skipped"]
RunPhase = Literal["created", "running", "awaiting_gate", "succeeded", "failed", "cancelled", ...]
class NodeState(_Frozen): node_id; status: NodeStatus = "idle"; started_at; finished_at; error; dispatch; summary
class DevLoopSessionState(_Frozen): run_id; channel; phase: RunPhase; nodes: Dict[str, NodeState]; gates; ...

# From packages/ai-parrot/src/parrot/flows/dev_loop/streaming.py:73
class FlowStreamMultiplexer:  replay(); tail(); state_replay(); state_tail()

# From packages/ai-parrot-server/src/parrot/handlers/a2ui.py:84, :225, :293
class A2UIHandler(AgentTalk):
    async def get(self) -> web.StreamResponse
    async def _get_stream(self) -> web.StreamResponse    # text/event-stream, one event per A→R envelope

# From packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py:41, :59, :68, :128
_SERIES_TYPE = {...}                                     # bar/line/area/scatter/pie/donut/radar/gauge/funnel/treemap/heatmap → ECharts series type
_ROW_NATIVE_TYPES = frozenset({"gauge", "funnel", "treemap", "heatmap", "waterfall", "radar"})
@register_a2ui_renderer(..., RendererCapabilities(..., supported_components={"Chart"}))   # bare name
def _build_option(self, props: dict[str, Any]) -> dict[str, Any]

# From packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py:120, :562
_INTERCEPTED = {"Chart", "DataTable", "Infographic", "Map", "HtmlDocument"}   # bare names
# ssr_html.py:129, pdf.py:96, adaptive_cards.py:218, folium_map.py:269 — supported_components sets, bare names

# From packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/pdf.py:50
def _chart_svg(props: dict) -> str                        # hand-drawn bar chart only; to be replaced

# From packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UINode.svelte:62-133
#   `{#if component === 'KPICard'} … {:else if component === 'Chart'} …` — dispatch on BARE name; `catalogId` not read.
```

#### Verified Imports
```python
from parrot.outputs.a2ui.catalog import register_component, get_component, list_components, catalog_instructions, resolve_catalog, validate_envelope
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree, ProducerOrigin, DEFAULT_CATALOG_ID, CatalogValidationError
from parrot.outputs.a2ui.catalog.basic import BASIC_CATALOG_ID, load_spec, basic_components
from parrot.outputs.a2ui.catalog.parrot._derive import derive_schema
from parrot.outputs.a2ui.catalog.export import export_catalog_definition, write_catalog_definition
from parrot.outputs.a2ui.models import Component, ChildTemplate, Action, UpdateDataModel, CreateSurface
from parrot.outputs.a2ui.renderers import RendererCapabilities, register_a2ui_renderer
from parrot.outputs.a2ui.renderers.degrade import degradation_record, degrade
from parrot.models.outputs import StructuredChartConfig
from parrot.models.infographic import ChartType
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition, EdgeDefinition   # callers/tests only
from parrot.flows.dev_loop.session_state import DevLoopSessionState, NodeState, NodeStatus
```

#### Key Attributes & Constants
- Three catalog ids in play: `BASIC_CATALOG_ID` (official), `DEFAULT_CATALOG_ID =
  "https://parrot.dev/catalogs/v1"` (Parrot), and the authored viz-core id
  `https://ai-parrot.dev/a2ui/catalogs/viz-core/1.0/catalog.json` (not yet a constant).
- Vendored `common_types.json#/$defs` contains `DynamicString`, `DynamicValue`,
  `DynamicNumber`, `ChildList`, `Action`, `ComponentCommon` (properties `id`,
  `catalogId`, `accessibility`, `metadata` — **`action` is not in `ComponentCommon`**;
  each viz-core component schema must declare `action` itself, as Parrot's `Component`
  model already accepts it).
- `Timeline` current schema: `title`, `events[{timestamp, title, description}]`, required `events` (catalog/parrot/timeline.py:16)
- `parrot_variant` / `parrot_role` vocabularies documented in `docs/frontend/agentdashboard-a2ui-reference.md:380-381` and `docs/outputs/a2ui-v1.md` ("metadata.extensions")
- Bundled UI deps present: `echarts ^5.0.0`, `d3-geo`, `d3-scale`, `svelte ^5.55.7` (packages/ai-parrot-server/ui/package.json)
- Satellite extras present: `matplotlib`, `plotly`, `altair`, `cairosvg`, `weasyprint>=68.0` (packages/ai-parrot-visualizations/pyproject.toml:38-60)
- All six satellite renderers currently declare `supports_updates=False`
- Mermaid is a vetted library entry in `parrot/models/interactive.py:52` (legacy interactive lane only)
- `DesignSystem` tokens available for the semantic roles: `--accent-green`, `--accent-amber`, `--accent-red`, `--accent-teal`, `--neutral-muted`, `--primary` (`formats/assets/design_system/base.css`, `components.css`)
- `artifacts/` is **not** gitignored (`git check-ignore` exit 1), so the two source artifacts can be committed alongside the spec that vendors them.

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.outputs.a2ui.catalog.viz_core` / `VIZ_CORE_CATALOG_ID` / `VIZ_CORE_INSTRUCTIONS`~~ — do not exist
- ~~viz-core `Chart`, `Series`, `Stat`, `Treemap` components; `coordinates`; `Stat.gauge`; `accessibleDescription` / `size` on any Parrot component~~ — do not exist
- ~~A `(catalog_id, name)`-keyed registry; `get_component(name, catalog_id=...)`; `list_components(catalog_id=...)`; `catalog_instructions(catalog_ids=...)`~~ — the registry and all three functions are bare-name / unscoped today
- ~~`selectAction`~~ — only in the authored draft; dropped in favour of the standard `action`
- ~~`Chart.spec` / `ChartSpec` union / `StructuredChartConfig.spec` / `DataContract` class attribute / `secondaryY`~~ — revision-1 sketches, superseded; never existed in code
- ~~`parrot.outputs.a2ui.catalog.parrot.graph` / `Graph` component~~ — does not exist (moves to viz-core in FEAT-529)
- ~~`parrot.outputs.a2ui.prepare`~~ — does not exist
- ~~`parrot.outputs.a2ui.graph.mermaid`~~ — does not exist; no mermaid parser anywhere in the repo
- ~~`parrot.outputs.a2ui.workflow` / `FlowSurfaceBridge` / `build_workflow_surface`~~ — do not exist
- ~~`parrot.outputs.a2ui.adapters.flow`~~ — does not exist
- ~~`builders.build_update_data_model` / `build_timeline` / `build_graph` / `build_viz_chart` / `build_stat` / `build_treemap`~~ — no such builders (only `build_surface`, `build_chart`, `build_kpicard`, `build_card`, `build_datatable`, `build_map`, `build_infographic`, `build_html_document`)
- ~~`Timeline.mode` / `lanes` / `playhead`~~ — not present
- ~~A2UI SSE stream carrying `updateDataModel`~~ — `_get_stream` delivers pending `callRendererFunction` only
- ~~Per-mark SVG rendering in SSR/PDF~~ — only `_chart_svg` bar chart
- ~~`ChartType` in `parrot.models.outputs`~~ — it lives in `parrot.models.infographic`
- ~~`packages/ai-parrot/src/parrot/outputs/a2ui/components/`~~ — the directory is `catalog/parrot/`
- ~~`catalogId` read anywhere in `A2UINode.svelte`~~ — the bundled UI dispatches on the bare `component` name
- ~~`mermaid`, `dagre`, `elkjs`, `@xyflow/*`, `vega*`, `layerchart` in `ui/package.json`~~ — not present; do not add

---

## Parallelism Assessment

- **Internal parallelism**: high across the three capabilities once the shell lands.
  Within `a2ui-graph-component`: shell ‖ graph models + lowering ‖ mermaid codec ‖
  layered layout, then builders/adapters, then renderers. Within `a2ui-viz-core-charts`:
  `Chart`/`Series`/`Stat`/`Treemap` models + preparers (core) ‖ ECharts option building
  ‖ static SVG module ‖ bundled UI, all behind the shell. Within
  `a2ui-live-workflow-surface`: `Timeline` v2 ‖ bridge + SSE ‖ agent function + runner
  wiring ‖ UI.
- **Cross-feature independence**: FEAT-527 is merged. `a2ui-graph-component` touches
  `catalog/__init__.py` (registry keying), `catalog/export.py`, `renderers/__init__.py`,
  `producer.py` and the renderers' interception tables — the charts spec touches the same
  files additively, so whichever merges second rebases on one-line set/branch additions.
  No overlap with FEAT-523 (PEP-420 respec), FEAT-526 (Meta client) or FEAT-528
  (recipe store).
- **Recommended isolation**: per-spec (three worktrees, sequenced graph → charts →
  live for merges; charts may start once the shell commit lands in the graph worktree).
- **Rationale**: the three capabilities share only the shell, the `parrot_vendor` gate
  and the `parrot_role` vocabulary, which are small and land first; everything else is
  disjoint files.

---

## Open Questions

- [x] Umbrella or single sub-project first? — *Owner: Jesus Lara*: umbrella brainstorm, then three specs
- [x] Who authors rich specs? — *Owner: Jesus Lara*: both tiers on one wire; LLM intent-level, code full-detail
- [x] Which renderers native in v1? — *Owner: Jesus Lara*: all four (Svelte navigator, backend ECharts/interactive-html, bundled UI, SSR/PDF)
- [x] Mermaid on the wire? — *Owner: Jesus Lara*: structured nodes/edges; codec both ways
- [x] Where does data-shaping knowledge live? — *Owner: Jesus Lara*: declared per-form contract + server-side preparer (viz-core rule 3)
- [x] Extension mechanism? — *Owner: Jesus Lara*: Option D grammar catalog plus tool-only `parrot_vendor` hint
- [x] Live updates channel? — *Owner: Jesus Lara*: FEAT-469 SSE stream (second source), not the dev-loop WebSocket
- [x] Drill-down path? — *Owner: Jesus Lara*: deterministic agent function, no LLM turn
- [x] interactive-html gauge/treemap/waterfall? — *Owner: Jesus Lara*: keep Chart.js, record degradation (bundled UI goes native via echarts) — applies to viz-core envelopes; legacy lane unchanged
- [x] (rev 2) How does viz-core relate to the Parrot `Chart`/`KPICard`? — *Owner: Jesus Lara*: separate catalog id; Parrot `Chart`/`KPICard` stay for FEAT-527 recipes and navigator-frontend-next; renderers dispatch on `(catalogId, name)`; no deprecation this round
- [x] (rev 2) How are gauge, radar, funnel, waterfall and treemap represented? — *Owner: Jesus Lara*: hybrid — `Chart.coordinates: polar` for radar; funnel and waterfall as server-prepared bar recipes; `Stat.gauge{min,max,bands,target}`; one new `Treemap` component
- [x] (rev 2) Where does `Graph` live and how far does it adopt viz-core? — *Owner: Jesus Lara*: under viz-core; adopts `accessibleDescription`, `size`, standard `action` with `nodeId` context, semantic status mapping for node state; `layout.positions` stays (layout is preparation, not styling)
- [x] (rev 2) Who lands the viz-core catalog shell? — *Owner: Jesus Lara*: FEAT-529 `a2ui-graph-component`; order becomes graph → charts → live surface
- [x] (rev 2) `selectAction` prop or standard `action`? — *Owner: Jesus Lara*: standard component-level `action` (the existing gate checks only that prop); renderer adds `{seriesId, x, y}` / `{nodeId, nodeLabel}` to the context
- [x] (rev 2) One y axis or `secondaryY`? — *Owner: Jesus Lara*: one y axis per `Chart`; `secondaryY` dropped
- [ ] (rev 2) Catalog id domain: keep the authored `https://ai-parrot.dev/a2ui/catalogs/viz-core/1.0/catalog.json`, or align with the Parrot catalog's `https://parrot.dev/catalogs/...` domain? Default: keep as authored (the artifacts are the reference). — *Owner: Jesus Lara*
- [ ] (rev 2) Does `Timeline` v2 also move under viz-core (with `size`/`accessibleDescription`/status roles), or stay in the Parrot catalog? Decide in `a2ui-live-workflow-surface`. — *Owner: Jesus Lara*
- [ ] (rev 2) Long-term fate of the Parrot `Chart`/`KPICard` once navigator-frontend-next speaks viz-core: deprecate, or keep as the "recipe" lane indefinitely? Not this round. — *Owner: Jesus Lara*
- [ ] Should `interactive-html` gain an SSE-subscribing variant so the backend HTML lane can show live workflow runs, or is that navigator/bundled-UI only in v1? — *Owner: Jesus Lara*
- [ ] Default animation duration and easing to document for `supports_updates` renderers (proposed 300 ms ease-in-out). — *Owner: Jesus Lara*
- [ ] Node-count threshold for static graph layout truncation (proposed 200). — *Owner: Jesus Lara*
- [ ] Should `describe_flow_node` be a generic `AgentsFlow` function or dev-loop specific in v1? — *Owner: Jesus Lara*
