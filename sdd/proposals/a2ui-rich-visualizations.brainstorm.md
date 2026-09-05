---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: A2UI rich visualizations — typed chart specs, `Graph` with mermaid codec, live workflow surfaces

**Date**: 2026-09-05
**Author**: Jesus Lara (with Claude)
**Status**: accepted
**Recommended Option**: B (plus a tool-only vendor hint)
**Builds on**: FEAT-527 `infographic-a2ui-migration` (chart-type parity), FEAT-470 `a2ui-v1-dialect` (wire + catalog), FEAT-469 `a2ui-agent-functions` (runtime RPC + SSE stream), FEAT-473 `a2ui-v1-structured-outputs` (schema parity by construction)

---

## Problem Statement

FEAT-527 makes every infographic turn emit an A2UI envelope and widens `ChartType`
with `gauge`, `funnel`, `waterfall`, `heatmap`, `treemap`. But the `Chart` catalog
component still describes every type with the same vocabulary: `type`, `x`, `y` and a
handful of styling flags. A renderer receiving `{"type": "gauge", "x": "kpi", "y":
["value"]}` has no idea what the gauge's range or bands are; a radar has no indicator
list; a scatter has no size or colour dimension; a heatmap has no matrix contract. The
renderer either guesses or degrades, and the agent has no place to say what it means.

Three related gaps block the surfaces users are asking for:

1. **Granularity.** Specialized objects (gauges, radar, scatter, heatmaps, treemaps,
   waterfalls) need per-type configuration and a per-type data shape. Today neither the
   wire nor any preparer knows those shapes, so the LLM must produce exactly the right
   DataFrame by luck, and every renderer re-implements the pivot logic.
2. **Structure.** There is no graph, DAG or flow component in the Parrot catalog.
   Mermaid exists only as a vetted library in the legacy interactive-HTML lane
   (`parrot/models/interactive.py`). Agents that reason about workflows (the dev loop,
   `AgentsFlow` definitions, dependency graphs) cannot render them as A2UI.
3. **Liveness.** `Timeline` is a static list of `{timestamp, title, description}`. An
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
- **Two authoring tiers on one wire.** The LLM authors a small intent-level spec through
  the existing validate-retry-degrade producer; deterministic code (tools, recipes, flow
  runners) authors full-detail specs. Same component, same schema, different depth.
- **Data contracts are declared, preparation is server-side.** Each visualization type
  states the row shape it needs; a deterministic Python preparer validates or reshapes the
  data before the envelope is built. The LLM names columns and roles only.
- **Mermaid compatibility both ways.** The wire carries typed nodes and edges; a pure
  Python codec imports mermaid text into that shape and exports it back.
- **FEAT-470 invariants hold.** A2UI core imports nothing from `parrot.bots` or
  `parrot.clients`; `lower()` is mandatory for every composite; presentation semantics
  outside the schema live under `metadata.extensions.parrot_*`; the D10b origin gate
  (`ProducerOrigin.LLM` may not carry actions) is reused, not duplicated.
- **FEAT-473 schema parity by construction.** New vocabulary is Pydantic first and fed to
  `derive_schema`; no hand-maintained JSON Schema for chart specs.
- **Additive to FEAT-527.** Every envelope FEAT-527 emits stays valid; `spec` and the new
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
- The Parrot catalog roughly doubles (9 → ~18 composites); every renderer's
  `supported_components` table and every degradation matrix grows with it.
- The LLM producer prompt grows with every new instruction block.
- Overlaps awkwardly with `Chart{type: "gauge"}`, which FEAT-527 already ships; two ways
  to say the same thing.
- The workflow surface becomes a monolithic component instead of a composition.

📊 **Effort:** High

📦 **Libraries / Tools:** none beyond Option B's.

🔗 **Existing Code to Reuse:**
- `parrot/outputs/a2ui/catalog/__init__.py` — `register_component`
- `parrot/outputs/a2ui/catalog/parrot/chart.py` — pattern for a derived-schema composite

---

### Option B: Typed `spec` on `Chart` + `Graph` composite + `Timeline` v2 (recommended)

`Chart` keeps its intent-level fields and gains an optional `spec` whose JSON Schema is a
`oneOf` keyed on `type`, derived from a Pydantic discriminated union of per-type spec
models. Each spec declares a `DataContract`; a server-side preparer reshapes rows to it.
Structure gets one new composite, `Graph`, with typed nodes, edges, layout hints,
bindable per-node state and a Python mermaid codec. Time gets an additive `Timeline` v2
(lanes, spans, state, live playhead). The live workflow surface is a **composition**
(`Graph` + `Timeline` + detail card) fed by a flow-event bridge that emits
`updateDataModel`.

✅ **Pros:**
- Additive to FEAT-527; one interception point per renderer for charts.
- Schema parity by construction preserved (`derive_schema` over Pydantic models).
- Two authoring tiers fall out naturally: `spec` absent = intent tier, present = detail
  tier.
- Workflow surface reuses `Graph`/`Timeline` for any `AgentsFlow`, not only the dev loop.
- Splits cleanly into three follow-on specs.

❌ **Cons:**
- `oneOf` conditional schema is harder for the LLM than flat props; mitigated by keeping
  `spec` optional and by per-type sub-instructions.
- Static SVG rendering for seven chart families plus graph layout is real work in Python.
- Hand-written mermaid tokenizer is a maintenance surface.

📊 **Effort:** High (spread across three specs)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (present) | discriminated union for `ChartSpec` | `Field(discriminator="type")` |
| `jsonschema` (present, FEAT-470 G8) | validates `oneOf` spec on the wire | already a hard core dep |
| `pandas` (present, core hard dep) | preparer reshaping | imported lazily inside preparer functions |
| `echarts` (present in bundled UI + satellite) | gauge/radar/scatter/heatmap/treemap/funnel/graph series | no new dep |
| `weasyprint` (present, PDF) | rasterizes SSR HTML with inline SVG | no JS |
| none | mermaid codec, layered graph layout | hand-written, pure Python |

🔗 **Existing Code to Reuse:**
- `parrot/outputs/a2ui/catalog/parrot/_derive.py` — `derive_schema`
- `parrot/outputs/a2ui/catalog/base.py` — `ProducerOrigin`, D10b gate
- `parrot/outputs/a2ui/models.py` — `UpdateDataModel`, `Extensions`
- `parrot/outputs/a2ui/builders.py` — `build_chart` pattern
- `parrot/outputs/a2ui/adapters/structured.py` — `chart_to_surface` (preparer call site)
- `parrot/outputs/a2ui/adapters/infographic.py` — `infographic_response_to_envelope` (second call site)
- `parrot/bots/flows/flow/definition.py` — `NodeDefinition`, `EdgeDefinition`, `FlowDefinition`
- `parrot/bots/flows/flow/flow.py` — `add_node_event_listener`, `_notify_node_event`
- `parrot/flows/dev_loop/session_state.py` — `DevLoopSessionState`, `NodeState`, `NodeStatus`
- `parrot/flows/dev_loop/streaming.py` — `FlowStreamMultiplexer` (state replay semantics)
- `ai-parrot-server/.../handlers/a2ui.py` — `A2UIHandler._get_stream` (SSE channel)
- `ai-parrot-visualizations/.../a2ui_renderers/echarts.py` — `_SERIES_TYPE`, `_build_option`
- `ai-parrot-visualizations/.../a2ui_renderers/pdf.py` — `_chart_svg` (to be replaced)

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

## Recommendation

**Option B, plus a bounded, tool-only version of Option C as a hint.**

Option B is the only option that satisfies the four-renderer constraint and keeps the
two authoring tiers on one wire. It reuses FEAT-473's schema derivation, FEAT-470's
extension namespace and origin gate, and FEAT-469's runtime and SSE stream, so most of
the new surface is vocabulary and adapters rather than machinery. The workflow surface as
a composition means `Graph` and `Timeline` v2 pay for themselves outside the dev loop.

The vendor hint is kept because deterministic tools sometimes have a tuned ECharts option
or an existing mermaid diagram and should not have to lose fidelity to fit the typed
spec. It is constrained so it can never become the primary description: `TOOL` origin
only, typed `spec` always mandatory alongside it, and every use recorded on the artifact.

Option A is rejected for catalog growth and the `Chart{type}` overlap. Option C alone is
rejected for renderer neutrality and validation.

---

## Feature Description

### User-Facing Behavior

- An agent asked for "a gauge of on-time delivery against the 95% target with red /
  amber / green bands" produces a `Chart{type: "gauge", spec: {...}}` that every
  renderer draws as a gauge with those bands, not a one-bar chart or a text summary.
- An agent asked to "show the dev-loop workflow" returns a `Graph` drawn as a flowchart.
  The same graph can be exported as mermaid text for a README, and a mermaid diagram
  pasted by a user can be imported into a surface.
- An operator opens a running dev-loop session and sees a graph whose nodes change
  colour as they start, complete or fail, a swimlane timeline with a moving playhead, and
  a detail panel that fills in when a node is clicked. No page reload, no LLM turn per
  click.
- Consumers that ignore `spec`, `Graph` and the new `Timeline` fields see today's output
  unchanged; static PDFs show a real gauge, radar or flowchart instead of a data summary.

### Internal Behavior

**Wire (Section 1 of the design).**
- `Chart` gains optional `spec`. `ChartSpec = Annotated[Union[CartesianSpec, GaugeSpec,
  RadarSpec, ScatterSpec, HeatmapSpec, TreemapSpec, FunnelSpec, WaterfallSpec],
  Field(discriminator="type")]` lives in `parrot/models/outputs.py` next to
  `StructuredChartConfig`, which gains `spec: Optional[ChartSpec]`. `derive_schema`
  picks it up, so `CHART_SCHEMA` gains `spec` with a `oneOf` by construction.
  - `GaugeSpec`: `min`, `max`, `bands[{from, to, color, label?}]`, `target?`, `format?`
  - `RadarSpec`: `indicators[{name, max?}]`, `fill: bool`, `seriesRole: str`
  - `ScatterSpec`: `sizeRole?`, `colorRole?`, `labelRole?`, `regression?: "linear"|"none"`
  - `HeatmapSpec`: `rowRole`, `colRole`, `valueRole`, `scale: "linear"|"log"|"quantile"`, `palette?`
  - `TreemapSpec`: `parentRole?`, `valueRole`, `depth?`
  - `FunnelSpec`: `stepRole`, `valueRole`, `sort: "asc"|"desc"|"none"`
  - `WaterfallSpec`: `stepRole`, `deltaRole`, `totalSteps?: list[str]`
  - `CartesianSpec`: axis formats, `yScale`, `secondaryY?`, `annotations[]`, `markLines[]`
  Every spec model embeds a `DataContract` class attribute (see below).
- Vendor hint: `metadata.extensions.parrot_vendor = {echarts?: dict, mermaid?: str}`.
  `validate_envelope(origin=LLM)` rejects it (extends the D10b gate). Renderers that use
  it set `RenderedArtifact.metadata["hintUsed"] = [component ids]`.

**Data preparation (Section 2).**
- New core package `parrot/outputs/a2ui/prepare/`: `contracts.py` (`DataContract{roles:
  [{name, kind: "category"|"value"|"series"|"row"|"col"|"size"|"color"|"label",
  required, aggregation?}], cardinality: "one"|"per-category"|"per-point"|"matrix"|
  "ordered"}`, per-type table), `preparers.py` (`prepare_chart_data(rows_or_df, config)
  -> PreparedData{rows, report}`), `errors.py` (`DataContractError` subclassing
  `CatalogValidationError` so the producer's retry loop already handles it).
- Output shapes: gauge → one row `{value, target?}`; radar → one row per series, one
  column per indicator; scatter → one row per point; heatmap → dense `{row, col, value}`
  with `null` fill; treemap/funnel/waterfall → ordered rows; cartesian → unchanged.
- Report attached under `metadata.extensions.parrot_preparation` (`rowsIn`, `rowsOut`,
  `aggregation`, `dropped`, `warnings`).
- Call sites: `chart_to_surface()` before binding rows; `infographic_response_to_envelope()`
  for chart blocks. Both deterministic; the LLM never calls the preparer.
- Pandas imported lazily inside preparer functions; accepts DataFrame or list of dicts.

**`Graph` composite and mermaid codec (Section 3).**
- `catalog/parrot/graph.py`, registered `Graph`, `allowed_parents = ["root", "Column",
  "Card", "Infographic", "Report"]`. Schema: `kind: flowchart|state|sequence|dag`,
  `direction: TB|LR|BT|RL`, `nodes[{id, label, shape?: rect|rounded|diamond|circle|
  hexagon|subroutine, group?, state?: pending|running|completed|failed|skipped|waiting,
  icon?, meta?}]`, `edges[{from, to, label?, kind?: solid|dashed|thick, condition?}]`,
  `groups[{id, label, nodes[]}]`, `layout{engine: layered|force|manual, rankSep?,
  nodeSep?, positions?}`, `selection{selectable, selected?}`, `data` (binding to an
  object keyed by node id overlaying `state`/`meta`/`label`), `nodeAction{event,
  contextFrom}` (TOOL origin only).
- `build_graph(...)` in `builders.py`; `adapters/flow.py::flow_definition_to_graph
  (FlowDefinition) -> Component` (node `type` → shape; `condition`/`predicate` → edge
  label; fan-out `to: list` → one edge each). Pure; no `parrot.bots` runtime import
  (`FlowDefinition` is a Pydantic model in `parrot/bots/flows/flow/definition.py`, so
  the adapter imports the model module only, and the G8 adapter import-rule test
  `packages/ai-parrot/tests/outputs/a2ui/adapters/test_import_rule.py` is extended to
  allow exactly that module).
- `parrot/outputs/a2ui/graph/mermaid.py`: `to_mermaid(component) -> str`,
  `from_mermaid(text) -> Component`. Dialects: `flowchart` (incl. `subgraph`),
  `stateDiagram-v2`, `sequenceDiagram` (participants → nodes, messages → ordered edges).
  Hand-written tokenizer; `MermaidCodecError(line, reason)` subclassing
  `CatalogValidationError`. Round-trip asserted on every golden.
- Lowering: `Card{Column[Text title, Text "A → B (label)" per edge (parrot_role: edge),
  Text mermaid source (parrot_role: graph-source)]}`, `parrot_variant: graph`.
- Static: `ai-parrot-visualizations/.../a2ui_renderers/_graph_layout.py` pure-Python
  layered layout (rank assignment, barycentre crossing reduction, coordinate assignment)
  → SVG with shapes, edge paths, labels, state colours from `DesignSystem`. Force layout
  degrades to layered with a `degraded` record.

**`Timeline` v2 and live workflow surface (Section 4).**
- `Timeline` additive fields: `mode: list|gantt|live` (default `list`), `lanes[{id,
  label}]`, events gain `id`, `lane`, `start`, `end`, `state`, `progress`, `parent`,
  `meta`; `range{start, end?}` (open end = now); `playhead` (`DynamicString` binding);
  `data` binding overlaying per-event fields; `eventAction` (TOOL origin only). Lowering
  degrades `gantt`/`live` to the row list with `state` as a badge.
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

| Renderer | Chart.spec | Graph | Timeline v2 | Updates / actions |
|---|---|---|---|---|
| navigator-frontend-next (Svelte 5) | all types native | layered + force | list/gantt/live | SSE updates, actions |
| bundled UI `canvas/a2ui` | all types native (echarts) | layered (d3) | list/gantt/live | SSE updates, actions |
| ECharts (satellite) | all types native (`_SERIES_TYPE` extended) | ECharts `graph` series | gantt via custom series | none (static HTML) |
| interactive-html | Chart.js cartesian; gauge/treemap/waterfall degrade (recorded) | Python layered SVG | list/gantt static | none in v1 |
| SSR-HTML / PDF | Python SVG per type (replaces `_chart_svg`) | Python layered SVG | gantt SVG | none |
| Adaptive Cards / Folium | lowering only | lowering only | lowering only | as today |

### Edge Cases & Error Handling

- `spec.type` disagrees with `Chart.type` → schema validation error (the `oneOf`
  discriminator); LLM lane retries once then degrades, TOOL lane raises.
- `spec` absent for a new type → renderer defaults (gauge 0..100, radar max = column
  max, scatter no size/colour). Documented per type in `CHART_INSTRUCTIONS`.
- `DataContractError` (missing role, wrong cardinality, non-numeric value column) →
  message carries role, expected shape and a repair hint; producer feeds it to the
  repair prompt; never renders a wrong chart silently.
- Heatmap with sparse cells → dense fill with `null`; renderer paints missing as empty.
- Preparer receives more rows than the contract allows and no aggregation declared →
  `DataContractError` (no implicit aggregation).
- `Graph` with an edge to an unknown node, a cycle in `kind: dag`, or `manual` layout
  without `positions` → validation error at build time.
- `from_mermaid` meets an unsupported construct (class diagrams, `click` directives,
  styling blocks) → `MermaidCodecError` naming the line; nothing is silently dropped.
- `to_mermaid` on a node label containing mermaid-reserved characters → quoted label.
- `Graph.data` binding resolves to an object missing some node ids → those nodes keep
  their static `state`.
- Bridge: `updateDataModel` for a node id not in the surface is ignored by the renderer
  (v1.0 semantics); the bridge logs at debug. SSE client disconnect → bridge drops that
  subscriber; the flow run is unaffected.
- Drill-down on a node with no `NodeState` yet → `/selected` gets `{nodeId, state:
  "pending"}` and the detail card shows "not started".
- Vendor hint present on an `LLM`-origin envelope → rejected with the existing
  `UNALLOWED_*` code family; on `TOOL` origin without a typed `spec` → rejected (hint
  never stands alone).
- Static layout for graphs above a size threshold (e.g. 200 nodes) → truncate with a
  recorded `degraded` entry rather than time out.

---

## Capabilities

### New Capabilities
- `a2ui-typed-chart-specs`: `ChartSpec` discriminated union on `Chart`, `DataContract`
  per type, `parrot/outputs/a2ui/prepare/` preparer, preparer wiring in both adapters,
  tool-only `parrot_vendor` hint + gate, ECharts native series for all types, Python
  static SVG per type for SSR/PDF, bundled UI + Svelte contract doc for `spec`.
- `a2ui-graph-component`: `Graph` composite, `build_graph`, `flow_definition_to_graph`,
  mermaid codec (flowchart, stateDiagram-v2, sequenceDiagram), lowering, pure-Python
  layered layout → SVG, ECharts graph series, bundled UI + Svelte contract doc.
- `a2ui-live-workflow-surface`: `Timeline` v2 fields and lowering, `build_workflow_surface`,
  `FlowSurfaceBridge`, SSE second source in `A2UIHandler`, `describe_flow_node` agent
  function, dev-loop runner wiring, renderer animation contract, gantt SVG.

Recommended order: typed chart specs → graph component → live workflow surface. The
third depends on the second's `Graph`; the second borrows the first's spec/contract
pattern and `parrot_vendor` gate.

### Modified Capabilities
- `infographic-a2ui-migration` (FEAT-527): `ChartType` widening and `CHART_TYPE_MAP` are
  prerequisites; this brainstorm adds `spec` on top and replaces the "Chart.js / bundled
  UI degrade with a recorded entry" rule for gauge/treemap/waterfall in the bundled UI
  (now native via echarts). interactive-html keeps degrading.
- `a2ui-v1-structured-outputs` (FEAT-473): `chart_to_surface` calls the preparer;
  `StructuredChartConfig` gains `spec`.
- `a2ui-agent-functions` (FEAT-469): `A2UIHandler._get_stream` gains a second event
  source (bridge updates); a new registered agent function `describe_flow_node`.
- `a2ui-v1-dialect` (FEAT-470): `Timeline` schema widened (additive); D10b gate extended
  to `parrot_vendor`; `parrot_role` vocabulary gains `edge`, `graph-source`, `lane`,
  `span`, `playhead`.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/models/outputs.py` (`StructuredChartConfig`, new `ChartSpec` union) | extends | `spec: Optional[ChartSpec]`; discriminator on `type` |
| `parrot/outputs/a2ui/catalog/parrot/chart.py` | modifies | `CHART_SCHEMA` gains `spec` via `derive_schema`; `CHART_INSTRUCTIONS` per-type sub-instructions |
| `parrot/outputs/a2ui/catalog/parrot/timeline.py` | extends | v2 fields, `gantt`/`live` lowering |
| `parrot/outputs/a2ui/catalog/parrot/graph.py` | creates | `Graph` composite |
| `parrot/outputs/a2ui/catalog/parrot/__init__.py` | modifies | import `graph` for registration |
| `parrot/outputs/a2ui/catalog/__init__.py` (`validate_envelope`) | extends | `parrot_vendor` gate (LLM reject; TOOL requires `spec`) |
| `parrot/outputs/a2ui/prepare/` | creates | contracts, preparers, errors |
| `parrot/outputs/a2ui/graph/mermaid.py` | creates | codec |
| `parrot/outputs/a2ui/workflow.py` | creates | `build_workflow_surface`, `FlowSurfaceBridge` |
| `parrot/outputs/a2ui/adapters/structured.py`, `adapters/infographic.py` | modifies | call preparer; forward `spec` |
| `parrot/outputs/a2ui/adapters/flow.py` | creates | `flow_definition_to_graph` |
| `parrot/outputs/a2ui/builders.py` | extends | `build_graph`, `build_timeline`, `build_update_data_model` |
| `parrot/outputs/a2ui/catalog/export.py` | modifies | new component + `describe_flow_node` function in `catalog_definition.json` |
| `parrot/outputs/a2ui/catalog/spec/` | none | vendored official schemas untouched (Parrot catalog only) |
| `ai-parrot-server/.../handlers/a2ui.py` | extends | SSE stream second source |
| `parrot/flows/dev_loop/runner.py` | extends | attaches `FlowSurfaceBridge`; registers `describe_flow_node` |
| `ai-parrot-visualizations/.../a2ui_renderers/echarts.py` | extends | `_SERIES_TYPE` + per-spec option building; `Graph` series; gantt custom series |
| `ai-parrot-visualizations/.../a2ui_renderers/ssr_html.py`, `pdf.py` | modifies | intercept `Chart`/`Graph`/`Timeline`; replace `_chart_svg` with per-type SVG module |
| `ai-parrot-visualizations/.../a2ui_renderers/_chart_svg.py`, `_graph_layout.py` | creates | static SVG + layered layout |
| `ai-parrot-visualizations/.../a2ui_renderers/interactive_html.py` | extends | `Graph`/`Timeline` static embed; recorded degradations |
| `ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/*` | extends | `spec`-aware chart, `Graph`, `Timeline` v2, SSE subscription |
| `docs/frontend/agentdashboard-a2ui-reference.md`, `docs/outputs/a2ui-v1.md` | docs | contract for `spec`, `Graph`, `Timeline` v2, `parrot_vendor`, bridge stream |
| Golden fixtures + conformance suite | extends | per type / per kind goldens; round-trip goldens |

No breaking changes on the wire. New hard dependencies: none. Optional: none.

---

## Code Context

### User-Provided Code

None. The user described the requirement in prose (this brainstorm's Problem Statement).

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

# From packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py:107
def register_component(
    name: str,
    *,
    requires_actions: bool = False,
    catalog_id: str = DEFAULT_CATALOG_ID,
    is_primitive: bool = False,
    allowed_parents: list[str] | None = None,
    allowed_children: list[str] | None = None,
) -> Callable[[type], type]: ...

# From packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py:85
class ProducerOrigin(str, Enum): ...   # LLM / TOOL; drives the D10b action gate

# From packages/ai-parrot/src/parrot/outputs/a2ui/models.py:341, :364
class Extensions(RootModel[dict[str, Any]]): ...   # parrot_* keys; official-prefix keys rejected
class ComponentMetadata(BaseModel):
    extensions: Extensions | None = None

# From packages/ai-parrot/src/parrot/outputs/a2ui/models.py:490
class UpdateDataModel(A2UIMessageBase):
    surface_id: str = Field(alias="surfaceId")
    path: str | None = None
    value: Any   # REQUIRED; explicit None deletes

# From packages/ai-parrot/src/parrot/outputs/a2ui/builders.py:97
def build_chart(*, chart_type: str, x: str, y: Sequence[str], title: str | None = None,
                data_binding: str | None = None, show_legend: bool = True, ...) -> CreateSurface

# From packages/ai-parrot/src/parrot/outputs/a2ui/adapters/structured.py:176
def chart_to_surface(...)          # preparer call site #1
# From packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py:599
def infographic_response_to_envelope(...)   # preparer call site #2

# From packages/ai-parrot/src/parrot/outputs/a2ui/baking.py:356, :399
def bake_envelope(envelope: CreateSurface) -> list[dict[str, Any]]
async def persist_envelope(...)

# From packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py:51
class RendererCapabilities(BaseModel):
    interactive: bool; supports_actions: bool; supports_updates: bool
    output: str; supported_catalog_ids: ...; supported_components: set[str]

# From packages/ai-parrot/src/parrot/models/outputs.py:319
class StructuredChartConfig(BaseModel):
    type: ChartType; x: str; y: List[str]; stacked; trendline; split_series; show_legend;
    x_axis_mode; palette; color_by_sign; negative_color; positive_color; x_axis_label;
    y_axis_label; map_name; title; description; data: List[dict]; data_variable

# From packages/ai-parrot/src/parrot/models/infographic.py:103
class ChartType(str, Enum):
    BAR, LINE, PIE, DONUT, AREA, SCATTER, RADAR, HEATMAP, TREEMAP, FUNNEL, GAUGE, WATERFALL

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
class FlowStreamMultiplexer:  replay(); tail(); state_replay(); state_tail()   # view="state" folds flow:{run_id}:actions via reduce()

# From packages/ai-parrot-server/src/parrot/handlers/a2ui.py:84, :225, :293
class A2UIHandler(AgentTalk):
    async def get(self) -> web.StreamResponse            # dispatches to _get_stream / capabilities / surface
    async def _get_stream(self) -> web.StreamResponse    # text/event-stream, one event per A→R envelope

# From packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py:41, :128
_SERIES_TYPE = {...}                                     # A2UI chart type → ECharts series type
def _build_option(self, props: dict[str, Any]) -> dict[str, Any]

# From packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/pdf.py:50
def _chart_svg(props: dict) -> str                        # hand-drawn bar chart only; to be replaced
```

#### Verified Imports
```python
from parrot.outputs.a2ui.catalog import register_component            # catalog/__init__.py:107
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree, ProducerOrigin   # catalog/base.py
from parrot.outputs.a2ui.catalog.parrot._derive import derive_schema   # _derive.py:88
from parrot.outputs.a2ui.models import Component, UpdateDataModel, CreateSurface   # models.py
from parrot.models.outputs import StructuredChartConfig               # models/outputs.py:319
from parrot.models.infographic import ChartType                       # models/infographic.py:103
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition, EdgeDefinition
from parrot.flows.dev_loop.session_state import DevLoopSessionState, NodeState, NodeStatus
from parrot.outputs.a2ui.renderers.degrade import degradation_record, degrade   # used by ssr_html.py:55
```

#### Key Attributes & Constants
- `Timeline` current schema: `title`, `events[{timestamp, title, description}]`, required `events` (catalog/parrot/timeline.py:16)
- `parrot_variant` / `parrot_role` vocabularies documented in `docs/frontend/agentdashboard-a2ui-reference.md:380-381`
- Bundled UI deps present: `echarts ^5.0.0`, `d3-geo`, `d3-scale`, `svelte ^5.55.7` (packages/ai-parrot-server/ui/package.json)
- Satellite extras present: `matplotlib`, `plotly`, `altair`, `cairosvg`, `weasyprint>=68.0` (packages/ai-parrot-visualizations/pyproject.toml:38-60)
- All six satellite renderers currently declare `supports_updates=False`
- Mermaid is a vetted library entry in `parrot/models/interactive.py:52` (legacy interactive lane only)

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.outputs.a2ui.catalog.parrot.graph` / `Graph` component~~ — does not exist
- ~~`parrot.outputs.a2ui.prepare`~~ — does not exist
- ~~`parrot.outputs.a2ui.graph.mermaid`~~ — does not exist; no mermaid parser anywhere in the repo
- ~~`parrot.outputs.a2ui.workflow` / `FlowSurfaceBridge` / `build_workflow_surface`~~ — do not exist
- ~~`parrot.outputs.a2ui.adapters.flow`~~ — does not exist
- ~~`builders.build_update_data_model` / `build_timeline` / `build_graph`~~ — no such builders (only `build_surface`, `build_chart`, `build_kpicard`, `build_card`, `build_datatable`, `build_map`, `build_infographic`)
- ~~`StructuredChartConfig.spec`~~ — not a field today
- ~~`Chart.spec` in `CHART_SCHEMA`~~ — not present
- ~~`Timeline.mode` / `lanes` / `playhead`~~ — not present
- ~~A2UI SSE stream carrying `updateDataModel`~~ — `_get_stream` delivers pending `callRendererFunction` only
- ~~Per-type SVG rendering in SSR/PDF~~ — only `_chart_svg` bar chart
- ~~`ChartType` in `parrot.models.outputs`~~ — it lives in `parrot.models.infographic`
- ~~`packages/ai-parrot/src/parrot/outputs/a2ui/components/`~~ — the directory is `catalog/parrot/`

---

## Parallelism Assessment

- **Internal parallelism**: high across the three capabilities once the shared pieces
  land. Within `a2ui-typed-chart-specs`: spec models + preparer (core) ‖ ECharts option
  building ‖ static SVG module ‖ bundled UI, all behind the `CHART_SCHEMA` change.
  Within `a2ui-graph-component`: schema + lowering + builders ‖ mermaid codec ‖ layered
  layout ‖ renderers. Within `a2ui-live-workflow-surface`: `Timeline` v2 ‖ bridge +
  SSE ‖ agent function + runner wiring ‖ UI.
- **Cross-feature independence**: conflicts with in-flight **FEAT-527** on
  `catalog/parrot/chart.py`, `adapters/infographic.py`, `a2ui_renderers/echarts.py`,
  `ssr_html.py`, `pdf.py`, `interactive_html.py` and `ui/.../canvas/a2ui/*`. The typed
  chart spec work must start after FEAT-527 TASK-2859/2861/2866 merge. `Graph` and the
  workflow surface touch none of FEAT-527's files except `catalog/parrot/__init__.py`
  and the renderers' interception tables, so they can begin in parallel with FEAT-527's
  tail. No overlap with FEAT-523 (PEP-420 respec) or FEAT-526 (Meta client).
- **Recommended isolation**: per-spec (three worktrees, sequenced 1 → 2 → 3 for
  merges; 2 may start before 1 merges).
- **Rationale**: the three capabilities share only the `parrot_vendor` gate and the
  `parrot_role` vocabulary, which are small and can be landed first by whichever spec
  merges first; everything else is disjoint files.

---

## Open Questions

- [x] Umbrella or single sub-project first? — *Owner: Jesus Lara*: umbrella brainstorm, then three specs
- [x] Who authors rich specs? — *Owner: Jesus Lara*: both tiers on one wire; LLM intent-level, code full-detail
- [x] Which renderers native in v1? — *Owner: Jesus Lara*: all four (Svelte navigator, backend ECharts/interactive-html, bundled UI, SSR/PDF)
- [x] Mermaid on the wire? — *Owner: Jesus Lara*: structured nodes/edges; codec both ways
- [x] Where does data-shaping knowledge live? — *Owner: Jesus Lara*: declared `DataContract` + server-side preparer
- [x] Extension mechanism? — *Owner: Jesus Lara*: Option B plus tool-only `parrot_vendor` hint
- [x] Live updates channel? — *Owner: Jesus Lara*: FEAT-469 SSE stream (second source), not the dev-loop WebSocket
- [x] Drill-down path? — *Owner: Jesus Lara*: deterministic agent function, no LLM turn
- [x] interactive-html gauge/treemap/waterfall? — *Owner: Jesus Lara*: keep Chart.js, record degradation (bundled UI goes native via echarts)
- [ ] Should `interactive-html` gain an SSE-subscribing variant so the backend HTML lane can show live workflow runs, or is that navigator/bundled-UI only in v1? — *Owner: Jesus Lara*
- [ ] Default animation duration and easing to document for `supports_updates` renderers (proposed 300 ms ease-in-out). — *Owner: Jesus Lara*
- [ ] Node-count threshold for static graph layout truncation (proposed 200). — *Owner: Jesus Lara*
- [ ] Should `describe_flow_node` be a generic `AgentsFlow` function or dev-loop specific in v1? — *Owner: Jesus Lara*
