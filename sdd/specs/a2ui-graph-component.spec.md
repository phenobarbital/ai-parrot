---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: A2UI `Graph` component under the `viz-core` catalog — catalog shell, typed nodes/edges, mermaid codec, layered layout

**Feature ID**: FEAT-529
**Date**: 2026-09-05 (v0.2, same day as v0.1)
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 0.30.0
**Source brainstorm**: `sdd/proposals/a2ui-rich-visualizations.brainstorm.md` (umbrella, **revision 2**: Option D viz-core grammar catalog for charts + Option B's `Graph`/`Timeline`; this spec is its `a2ui-graph-component` capability and now also carries the **viz-core catalog shell**)
**Source artifacts**: `sdd/proposals/assets/a2ui-viz-core/viz-core.catalog.json` (viz-core draft 0.1), `sdd/proposals/assets/a2ui-viz-core/viz-core.example.jsonl` (tracked copies; the user's working files under `artifacts/a2ui/` are gitignored)
**Sibling specs (same umbrella)**: `a2ui-viz-core-charts` (not yet written; depends on this spec's shell), `a2ui-live-workflow-surface` (not yet written; depends on this spec's `Graph`)

---

## 1. Motivation & Business Requirements

### Problem Statement

There is no graph, DAG or flow component in any Parrot A2UI catalog. Agents that reason
about workflows (the dev loop, `AgentsFlow` definitions, dependency graphs, state
machines, call sequences) cannot render them as an A2UI surface. Mermaid exists only as a
vetted library name in the legacy interactive-HTML lane (`parrot/models/interactive.py`),
so today a "show me the workflow" request either falls back to raw HTML the frontend
must iframe, or to a bullet list.

The umbrella brainstorm settled that the wire must carry **typed nodes and edges**, not
a mermaid string: per-node state must be bindable to the data model (so a later
`updateDataModel` recolours a node), per-node clicks must dispatch v1.0 actions, and all
four renderers (navigator-frontend-next, the bundled Svelte canvas, the backend
ECharts/interactive-HTML lane and the static SSR-HTML/PDF lane) must draw it natively
without each embedding a mermaid parser. Mermaid stays as a **codec**: import text into
the typed shape, export the typed shape back for documentation and mermaid-capable
consumers.

Revision 2 of the brainstorm adds a second requirement. Visualization vocabulary moves
into a **third A2UI catalog, `viz-core`** (design reference:
`artifacts/a2ui/viz-core.catalog.json`), whose rule is *describe what, never how*: no
colour, font, pixel or library option on the wire; semantic colour roles and formats;
size as intent; an `accessibleDescription` on every visual; the standard component-level
`action` for selection. `Graph` is the first viz-core component, so this spec also lands
the small **catalog shell** the whole umbrella needs: a catalog id constant, a registry
keyed by `(catalog_id, name)` (today it is keyed by bare name, so a second `Chart` could
not even register), catalog-scoped LLM instructions, the exporter for the viz-core
document, and renderer dispatch that reads the catalog id.

The `a2ui-live-workflow-surface` spec (animated dev-loop timeline with drill-down) is
blocked on this component: it composes `Graph` with `Timeline` v2 and pushes node state
over the FEAT-469 SSE stream. The `a2ui-viz-core-charts` spec is blocked on the shell.
This spec delivers the shell and the component; it delivers neither the charts nor the
live bridge.

### Goals

- **G0 — viz-core catalog shell.** `VIZ_CORE_CATALOG_ID` and `VIZ_CORE_INSTRUCTIONS`
  (the nine guideline rules from the draft) in a new core package
  `parrot/outputs/a2ui/catalog/viz_core/`; the component registry keyed by
  `(catalog_id, name)` with bare-name lookups preserved for unique names;
  `list_components(catalog_id=…)` and `catalog_instructions(catalog_ids=…)` scoped so the
  LLM producer sees only the catalogs its surface uses; `export_catalog_definition(
  catalog_id=VIZ_CORE_CATALOG_ID)` producing a document valid against the vendored
  `catalog_definition.json`; `RendererCapabilities.supported_catalog_ids` including
  viz-core on the lanes that draw it; renderer interception keyed by `(catalogId, name)`
  for viz-core entries; the bundled UI dispatching on `catalogId` + name.
- **G1 — `Graph` viz-core composite.** A new composite `Graph` registered under
  `VIZ_CORE_CATALOG_ID` with a Pydantic-first schema (`kind`, `direction`, `nodes[]`,
  `edges[]`, `groups[]`, `layout`, `selection`, `data` binding, plus the viz-core common
  props `size`, `accessibleDescription`, `action`), derived into `SCHEMA` by
  `derive_schema` (schema parity by construction, FEAT-473 G2), with a mandatory
  `lower()` to Basic primitives (FEAT-470 G4).
- **G2 — Bindable node state.** `Graph.data` is an optional data-model binding to an
  object keyed by node id whose values overlay `state`, `label` and `meta` at render time,
  so a graph authored once can be updated with `updateDataModel` alone.
- **G3 — Node click as a v1.0 action.** A `TOOL`-origin envelope may attach the standard
  component-level `action` to a `Graph` (declared in `GRAPH_SCHEMA` as `$ref
  common_types Action`, since `action` is not part of `ComponentCommon`); renderers that
  support actions dispatch it on node click with `context.nodeId` (and
  `context.nodeLabel`) added. The existing D10b gate rejects it on `LLM` origin; no new
  gate is introduced. The draft's `selectAction` is **not** adopted.
- **G4 — Mermaid codec both ways.** Pure-Python `to_mermaid()` / `from_mermaid()` for the
  `flowchart` (incl. `subgraph`), `stateDiagram-v2` and `sequenceDiagram` dialects, with
  a canonical form that round-trips, and `MermaidCodecError` naming the offending line for
  anything outside the supported subset. No external parser dependency.
- **G5 — Deterministic layered layout in core.** A pure-Python layered layout
  (rank assignment, barycentre crossing reduction, coordinate assignment, group bounding
  boxes) producing `layout.positions`, used by the builder at build time and by every
  renderer when positions are absent. `networkx` (already a core hard dependency) may be
  used for topological generations and cycle detection; no new dependency. Positions stay
  on the wire because a layout is **server-side preparation** (viz-core rule 3), not
  styling.
- **G6 — Builder and flow adapter.** `build_graph(...)` in `builders.py`, and
  `flow_definition_to_graph(...)` in `adapters/flow.py` that maps a `FlowDefinition`-shaped
  mapping (nodes/edges/conditions/fan-out) to a `GraphSpec` **without importing
  `parrot.bots`** (G8 import rule preserved as-is).
- **G7 — Native rendering on all four lanes.** ECharts (`graph` series, `layout: "none"`
  with positions), interactive-HTML and SSR-HTML/PDF (inline SVG from positions, node
  `state` mapped to the semantic status roles and painted with `DesignSystem` tokens),
  bundled Svelte canvas (`A2UIGraph.svelte` on the existing `ECharts.svelte` wrapper);
  navigator-frontend-next receives the contract in the frontend reference doc.
- **G8 — Useful degradation.** Lowering yields the `accessibleDescription`, the edge
  list and the mermaid source as `Text` nodes, so Adaptive Cards and any renderer
  without a graph engine (or without viz-core in `supported_catalog_ids`) show something
  readable and copyable rather than a placeholder. Force layout on static lanes and
  graphs above the static node cap degrade with a recorded `degraded` entry.
- **G9 — Invariants kept.** A2UI core imports nothing from `parrot.bots`/`parrot.clients`
  (`adapters/test_import_rule.py` unchanged); `version` only in `serialization.py`;
  presentation semantics outside the schema only under `metadata.extensions.parrot_*`;
  `test_no_exec.py` holds; every new builder validates against the vendored v1.0 schema
  in the conformance suite; **no colour value, font, pixel size or library option appears
  anywhere in `GRAPH_SCHEMA`**; the Parrot catalog (`DEFAULT_CATALOG_ID`) and every
  existing envelope shape are untouched.

### Non-Goals (explicitly out of scope)

- **viz-core `Chart`, `Series`, `Stat`, `Treemap`, `coordinates`, `Stat.gauge`, the
  complex-form mapping, preparers (`prepare/`), opt-in viz-core emission in the adapters,
  the `parrot_vendor` hint gate, the drift test against the authored draft** —
  `a2ui-viz-core-charts`. This spec's shell only has to be *sufficient* for those to land
  additively.
- **Live updates, SSE bridge, `describe_flow_node`, `Timeline` v2, animation contract** —
  `a2ui-live-workflow-surface`.
- **Any change to the Parrot catalog `Chart`/`KPICard`, `StructuredChartConfig`, the
  FEAT-527 recipe emitters or navigator-frontend-next's `AppChartConfig` lane** — legacy
  stays, no deprecation this round (brainstorm rev 2).
- **Mermaid dialects beyond flowchart / stateDiagram-v2 / sequenceDiagram** (class, ER,
  gantt, pie, gitGraph, mindmap), and mermaid `classDef`/`style`/`click`/`linkStyle`/
  `%%{init}` directives, notes, `loop`/`alt`/`par` blocks in sequences.
- **Force-directed layout on the server.** `layout.engine: "force"` is a hint for
  interactive renderers only; static lanes degrade to layered.
- **Editing graphs from the UI** (drag, add node), and persisting user-moved positions.
- **A mermaid string as the wire format**, **one component per graph kind**, and **a
  bespoke `selectAction`/`nodeAction` prop** — rejected in the brainstorm
  (`sdd/proposals/a2ui-rich-visualizations.brainstorm.md`, Options A/C and the rev-2
  resolved questions).
- **Changing navigator-frontend-next code** — contract doc only.
- **Rekeying the Basic or Parrot catalogs' component names, or renaming any existing
  component** — the shell adds a dimension; it moves nothing.

---

## 2. Architectural Design

### Overview

`Graph` follows the FEAT-470/473 composite pattern exactly: a Pydantic model family
(`GraphSpec` and children) is the single source of vocabulary; `derive_schema` turns it
into the wire `SCHEMA` with `data` replaced by the binding descriptor; `@register_component
("Graph", catalog_id=VIZ_CORE_CATALOG_ID)` publishes it into the **viz-core** catalog
and, through the existing exporter called with that id, into a viz-core
`catalog_definition.json`; `lower()` produces Basic primitives; renderers **intercept**
`Graph` before lowering (like `Chart`/`DataTable`/`Map`) and draw it natively.

**The shell (Module 0).** The registry `_CATALOG` becomes
`dict[tuple[str, str], RegisteredComponent]` keyed by `(catalog_id, name)`. Public
lookups keep their bare-name signatures and gain an optional `catalog_id`:
`get_component(name, catalog_id=None)` returns the unique registration for `name` when
`catalog_id` is omitted and exactly one catalog owns it, and raises `CatalogError` with
the candidate ids when the name is ambiguous — so the seven existing bare-name call sites
(`adapters/structured.py`, `catalog/parrot/infographic.py`, `catalog/parrot/report.py`,
`adaptive_cards.py`, `interactive_html.py` ×2, `ssr_html.py`) keep working unchanged
until the charts spec registers a viz-core `Chart`, at which point those that mean the
Parrot `Chart` must pass `DEFAULT_CATALOG_ID` (the charts spec owns that follow-up; this
spec adds the test that pins today's uniqueness). `_component_exists` uses the keyed
lookup. `list_components(catalog_id=None)` filters; `catalog_instructions(catalog_ids=
None)` emits `<name>: <instructions>` lines for the requested catalogs only, prefixed by
each catalog's own header block (Parrot's has none today; viz-core's is
`VIZ_CORE_INSTRUCTIONS`), and the producer passes the surface's default catalog plus the
ids of any components the caller pre-declares. `export_catalog_definition(catalog_id=
VIZ_CORE_CATALOG_ID, include_basic=True)` already filters by `definition.catalog_id`
and only needs the scoped instructions to emit a correct document;
`write_catalog_definition` gains a `catalog_id` parameter. `RendererCapabilities` keeps
its default `supported_catalog_ids`; the ECharts, interactive-HTML, SSR-HTML and PDF
renderers add `VIZ_CORE_CATALOG_ID` to theirs. Interception tables become sets of
`(catalog_id, name)` pairs with a helper `_intercepts(comp) -> bool` that resolves the
component's catalog (component `catalogId`, else the surface default) before lookup, so a
Parrot `Chart` and a future viz-core `Chart` are distinguishable. In the bundled UI,
`A2UINode.svelte` reads `catalogId` (falling back to the surface default) and dispatches
`Graph` only when it resolves to viz-core.

Three pure modules under a new core package `parrot/outputs/a2ui/graph/` carry the logic
renderers share: `models.py` (the Pydantic spec), `mermaid.py` (codec) and `layout.py`
(layered layout → positions). Putting layout in core rather than the satellite is what
lets the **builder** fill `layout.positions` at build time, so the bundled UI and ECharts
can draw with `layout: "none"` and every lane shows the same picture. Renderers still
call `compute_positions()` themselves when an envelope arrives without positions
(LLM-origin envelopes never carry them).

**viz-core alignment.** `GraphSpec` gains `accessible_description` (alias
`accessibleDescription`, a plain string; the lowered fallback's first line, and the
`<title>` of the SVG) and `size` (`inline|tile|hero`, default `tile`; renderers map it to
their own layout intent, never to pixels). Node `state` stays the domain enum
(`pending|running|completed|failed|skipped|waiting`) because it is *data*; the renderer
contract maps it to the viz-core semantic status roles — `completed → good`, `waiting →
warning`, `failed → critical`, `running → primary` emphasis, `pending`/`skipped →
neutral` — and paints those roles with its own theme (`DesignSystem` tokens on the
static lanes, Tailwind tokens in the bundled UI). `GRAPH_SCHEMA` therefore contains no
colour; the `icon` hint remains a free string (open question §8).

Node interaction stays inside v1.0: a `Graph` may carry the standard component-level
`action` (event or function call), declared in `GRAPH_SCHEMA` as `{"$ref":
"<common_types>#/$defs/Action"}` because `action` is not in the official
`ComponentCommon` (Parrot's `Component` model already accepts it). The renderer contract
adds `nodeId`/`nodeLabel` to the action's `context` when dispatching from a node click.
Because `action` presence is already rejected for `ProducerOrigin.LLM` by
`validate_envelope`, nothing new is gated.

`flow_definition_to_graph` accepts the **mapping form** of a `FlowDefinition`
(`definition.model_dump(by_alias=True)`) so `adapters/` never imports `parrot.bots`; the
G8 import-rule test stays untouched. Node `type` maps to a shape (`start`/`end` → circle,
`decision`/`interactive_decision` → diamond, `synthesis` → hexagon, `tool` → subroutine,
`agent` and `dev_loop.*` → rounded), `EdgeDefinition.condition` becomes the edge label
(`on_condition` → the CEL `predicate` text, `on_error`/`on_timeout` → dashed), fan-out
`to: [..]` becomes one edge per target.

### Component Diagram

```
        ┌──────────────── core: parrot/outputs/a2ui ─────────────────────────────────┐
        │ catalog/viz_core/__init__.py: VIZ_CORE_CATALOG_ID, VIZ_CORE_INSTRUCTIONS     │
        │ catalog/__init__.py: _CATALOG[(catalog_id, name)], get_component(name, cid), │
        │   list_components(cid), catalog_instructions(cids), _component_exists (keyed)│
        │ catalog/export.py: export_catalog_definition(catalog_id=VIZ_CORE…)           │
        └─────────────────────────────────────────────────────────────────────────────┘
FlowDefinition ─(model_dump)─▶ adapters/flow.py::flow_definition_to_graph ──┐
mermaid text ────────────────▶ graph/mermaid.py::from_mermaid ─────────────┤
LLM producer ─(validate-retry-degrade; instructions scoped to viz-core)────┤
                                                                            ▼
                    graph/models.py::GraphSpec ──▶ builders.build_graph ──▶ CreateSurface{Graph, catalogId: viz-core}
                          │                          │ (layout.positions filled
                          │                          │  via graph/layout.py)
                          ▼                          ▼
              catalog/viz_core/graph.py         validate_envelope (keyed catalog + D10b)
              SCHEMA = derive_schema(GraphSpec)      │
              lower() → Card{Column[description, title, edges…, mermaid source]}
                                                     ▼
   ┌───────────── renderers (intercept (viz-core, "Graph") before lowering) ──────────┐
   │ echarts.py: graph series, layout:"none"+positions   → option JSON / HTML        │
   │ interactive_html.py / ssr_html.py / pdf.py: _graph_svg.py (positions → SVG,     │
   │     state → status role → DesignSystem token)        → inline <svg>             │
   │ bundled UI canvas/a2ui/A2UIGraph.svelte on visualizations/ECharts.svelte        │
   │ adaptive_cards.py / folium_map.py: lowering only (description, edges, source)   │
   └────────────────────────────────────────────────────────────────────────────────┘
graph/mermaid.py::to_mermaid ◀── GraphSpec (docs export, lowering's graph-source Text)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/outputs/a2ui/catalog/__init__.py` | modifies | `_CATALOG` keyed by `(catalog_id, name)`; `get_component(name, catalog_id=None)`; `list_components(catalog_id=None)`; `catalog_instructions(catalog_ids=None)`; `_component_exists` keyed; gate lookup at :498 uses the resolved catalog id |
| `parrot/outputs/a2ui/catalog/viz_core/__init__.py` (new) | creates | `VIZ_CORE_CATALOG_ID`, `VIZ_CORE_INSTRUCTIONS`, registration import of `graph` |
| `parrot/outputs/a2ui/catalog/viz_core/spec/catalog.json` (new, vendored copy of `sdd/proposals/assets/a2ui-viz-core/viz-core.catalog.json`) | creates | design reference for the charts spec's drift test; **not** loaded at runtime here |
| `parrot/outputs/a2ui/catalog/viz_core/graph.py` (new) | creates | `GRAPH_SCHEMA = derive_schema(GraphSpec, …)`, `GRAPH_INSTRUCTIONS`, `@register_component("Graph", catalog_id=VIZ_CORE_CATALOG_ID)` |
| `parrot/outputs/a2ui/catalog/parrot/_derive.py::derive_schema` | uses | `derive_schema(GraphSpec, binding_fields=("data",), required=("nodes", "edges"))` |
| `parrot/outputs/a2ui/catalog/export.py` | extends | `write_catalog_definition(path, *, catalog_id=DEFAULT_CATALOG_ID)`; instructions scoped per exported catalog |
| `parrot/outputs/a2ui/producer.py` | modifies | `catalog_instructions(catalog_ids=[surface catalog, *component catalogs])` |
| `parrot/outputs/a2ui/renderers/__init__.py` | docs only | `supported_catalog_ids` docstring names viz-core; default unchanged |
| `parrot/outputs/a2ui/builders.py` | extends | `build_graph`; `__all__` updated; emits `catalogId: VIZ_CORE_CATALOG_ID` on the `Graph` component, surface default stays Parrot |
| `parrot/outputs/a2ui/adapters/__init__.py` | extends | export `flow_definition_to_graph` |
| `parrot/outputs/a2ui/baking.py` | none (automatic) | `Graph.data` binding is resolved by the existing bake pass like `Chart.data` |
| `a2ui_renderers/echarts.py` (visualizations) | extends | `supported_catalog_ids` += viz-core; `supported_components` adds `"Graph"`; `_build_graph_option()` |
| `a2ui_renderers/interactive_html.py` | extends | `_INTERCEPTED` → `(catalog_id, name)` pairs + `_intercepts()`; adds `(viz-core, "Graph")`; `_render_graph()` |
| `a2ui_renderers/ssr_html.py`, `pdf.py` | extends | `supported_catalog_ids` += viz-core; intercept `(viz-core, "Graph")` in `_lower_composites` → inline SVG; force-layout / node-cap degradation records |
| `a2ui_renderers/_graph_svg.py` (visualizations, new) | creates | positions + spec → SVG string; state → status role → `DesignSystem` token |
| `formats/assets/design_system` (`DesignSystem`) | uses | `--accent-green` (good), `--accent-amber` (warning), `--accent-red` (critical), `--primary` (running), `--neutral-muted` (neutral) |
| `ui/.../canvas/a2ui/A2UINode.svelte` | modifies | resolve `catalogId` (component, else surface default); `{:else if isVizCore && component === 'Graph'}` → `A2UIGraph.svelte` |
| `ui/.../canvas/a2ui/a2ui-types.ts` | extends | `catalogId?: string` on `WireComponent` (already `[prop]: unknown`; make it explicit) + `VIZ_CORE_CATALOG_ID` const |
| `ui/.../canvas/a2ui/A2UIGraph.svelte` (new) | creates | ECharts `graph` series via `visualizations/ECharts.svelte`; click → action dispatch hook (no-op in v1, see §8) |
| `docs/outputs/a2ui-v1.md`, `docs/frontend/agentdashboard-a2ui-reference.md` §5 | docs | "Three catalogs, one resolution rule"; viz-core principles; new `Graph` section; `parrot_role` additions |
| `tests/outputs/a2ui/conformance/test_all_emitters.py` | extends | `test_build_graph` |
| `tests/outputs/a2ui/golden/` | extends | `graph_lowered.json` |
| `tests/outputs/a2ui/catalog/test_export.py`, `test_validation_v1.py`, `test_catalog.py` | extends | keyed registry, scoped instructions, viz-core export validity |

### Data Models

```python
# parrot/outputs/a2ui/catalog/viz_core/__init__.py  (NEW — the shell's constants)
VIZ_CORE_CATALOG_ID: Final[str] = "https://ai-parrot.dev/a2ui/catalogs/viz-core/1.0/catalog.json"  # as authored; §8
VIZ_CORE_INSTRUCTIONS: Final[str] = "## Viz Core Guidelines\n\n1. Pick the form by the data's job … 9. Do not set metadata.extensions render hints unless a human asked …"  # verbatim from the artifact's `instructions`
```

```python
# parrot/outputs/a2ui/graph/models.py  (NEW — single source of Graph vocabulary)
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

GraphKind = Literal["flowchart", "state", "sequence", "dag"]
Direction = Literal["TB", "LR", "BT", "RL"]
NodeShape = Literal["rect", "rounded", "diamond", "circle", "hexagon", "subroutine"]
NodeState = Literal["pending", "running", "completed", "failed", "skipped", "waiting"]
EdgeKind = Literal["solid", "dashed", "thick"]
LayoutEngine = Literal["layered", "force", "manual"]
VizSize = Literal["inline", "tile", "hero"]          # viz-core common prop

class GraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: Optional[str] = None            # defaults to id on render
    shape: Optional[NodeShape] = None      # renderer default: rect (state kind: rounded)
    group: Optional[str] = None            # GraphGroup.id
    state: Optional[NodeState] = None      # DATA; renderer maps to a status role (see §2 Overview)
    icon: Optional[str] = None             # icon name hint (parrot_icon semantics, no asset)
    meta: Optional[dict[str, Any]] = None  # opaque; surfaced by renderers as tooltip

class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_: str = Field(alias="from")
    to: str
    label: Optional[str] = None
    kind: Optional[EdgeKind] = None        # default solid
    condition: Optional[str] = None        # free text (e.g. "on_error", CEL predicate)

class GraphGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: Optional[str] = None
    nodes: list[str]

class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float
    y: float

class GraphLayout(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    engine: LayoutEngine = "layered"
    rank_sep: Optional[float] = Field(default=None, alias="rankSep")   # abstract units, not pixels
    node_sep: Optional[float] = Field(default=None, alias="nodeSep")
    positions: Optional[dict[str, Position]] = None   # REQUIRED when engine == "manual"

class GraphSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selectable: bool = False
    selected: Optional[str] = None

class GraphSpec(BaseModel):
    """Wire vocabulary of the viz-core ``Graph`` composite (camelCase aliases on the wire)."""
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    kind: GraphKind = "flowchart"
    direction: Direction = "TB"
    title: Optional[str] = None
    accessible_description: Optional[str] = Field(default=None, alias="accessibleDescription")  # viz-core common prop
    size: VizSize = "tile"                                                                        # viz-core common prop
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    groups: Optional[list[GraphGroup]] = None
    layout: Optional[GraphLayout] = None
    selection: Optional[GraphSelection] = None
    # INPUT-ONLY: replaced by the {"path": ...} binding descriptor in the derived schema.
    # Resolves to {node_id: {"state"?: NodeState, "label"?: str, "meta"?: dict}}.
    data: Optional[dict[str, dict[str, Any]]] = None
    # NOTE: `action` is NOT a GraphSpec field — it is the Component-level prop. GRAPH_SCHEMA declares it
    # explicitly (see catalog/viz_core/graph.py) because common_types ComponentCommon lacks `action`.

# Model-level validators (GraphSpec): unique node ids; every edge endpoint exists;
# every group member exists and belongs to at most one group; kind == "dag" ⇒ acyclic;
# layout.engine == "manual" ⇒ positions covers every node.
# Forbidden-by-construction: no field of any model accepts a colour, font, pixel size or library option.
```

```python
# parrot/outputs/a2ui/graph/layout.py  (NEW)
MAX_STATIC_NODES: int = 200          # see §8 — graphs above this are truncated by static lanes

class LayoutResult(BaseModel):
    positions: dict[str, Position]   # abstract units, origin top-left, rank axis follows `direction`
    width: float
    height: float
    group_boxes: dict[str, tuple[float, float, float, float]]   # x, y, w, h per group id
    reversed_edges: list[tuple[str, str]]  # back edges reversed to break cycles (drawn with an arrow flip)
```

```python
# Renderer contract — node state → viz-core status role (documented, tested on the SVG lane)
STATE_TO_STATUS: Final[dict[str, str]] = {
    "completed": "good", "waiting": "warning", "failed": "critical",
    "running": "primary", "pending": "neutral", "skipped": "neutral",
}
# Static lanes: role → DesignSystem token (good→--accent-green, warning→--accent-amber, critical→--accent-red,
# primary→--primary, neutral→--neutral-muted). SVG nodes carry data-state and data-status attributes.
```

```python
# Lowered tree (catalog/viz_core/graph.py::GraphComponent.lower) — Basic primitives only
Card(id=<component.id>, metadata.extensions.parrot_variant="graph")
└─ Column
   ├─ Text <accessibleDescription | generated "Graph of N nodes and M edges (<kind>)">  parrot_role: description
   ├─ Text title                        parrot_role: title        (if title)
   ├─ Text "Graph (<kind>, <direction>)" parrot_role: caption
   ├─ Column                            parrot_role: edge-list
   │    └─ Text "<from> → <to> (<label>)" ×N   parrot_role: edge   (+ parrot_edge_kind, parrot_condition extensions)
   └─ Text <to_mermaid(spec)>           parrot_role: graph-source
# Any `data` binding passes through unresolved under metadata.extensions.parrot_graph_data
# (same convention as Chart's parrot_series_data) — resolved by the bake pass.
```

### New Public Interfaces

```python
# parrot/outputs/a2ui/catalog/__init__.py  (shell — signature changes; all backwards compatible)
_CATALOG: dict[tuple[str, str], RegisteredComponent]                 # (catalog_id, name)
def get_component(name: str, catalog_id: str | None = None) -> RegisteredComponent
    # catalog_id given → exact; omitted → unique match across catalogs, else CatalogError("ambiguous", candidates=[...])
def list_components(catalog_id: str | None = None) -> list[ComponentDefinition]
def catalog_instructions(catalog_ids: Sequence[str] | None = None) -> str
    # None → every catalog (today's behaviour); otherwise header block(s) + "<name>: <instructions>" lines for those catalogs
def catalog_header_instructions(catalog_id: str) -> str | None       # viz-core → VIZ_CORE_INSTRUCTIONS; others → None

# parrot/outputs/a2ui/catalog/viz_core/__init__.py
VIZ_CORE_CATALOG_ID: Final[str]; VIZ_CORE_INSTRUCTIONS: Final[str]

# parrot/outputs/a2ui/catalog/export.py
def write_catalog_definition(path: Path, *, catalog_id: str = DEFAULT_CATALOG_ID) -> None

# parrot/outputs/a2ui/graph/__init__.py
from .models import GraphSpec, GraphNode, GraphEdge, GraphGroup, GraphLayout, GraphSelection, Position, VizSize
from .mermaid import to_mermaid, from_mermaid, MermaidCodecError
from .layout import compute_positions, LayoutResult, MAX_STATIC_NODES, GraphTooLargeError

# parrot/outputs/a2ui/graph/mermaid.py
def to_mermaid(spec: GraphSpec) -> str: ...
    # Canonical form: header line from kind/direction; nodes declared once, in input order,
    # with shape brackets and quoted labels when needed; edges in input order; subgraph
    # blocks for groups. Deterministic (same spec → same text).
def from_mermaid(text: str) -> GraphSpec: ...
    # Raises MermaidCodecError(line_no, line, reason) — a CatalogValidationError subclass so
    # the LLM producer's validate-retry-degrade loop handles it without new plumbing.
class MermaidCodecError(CatalogValidationError):
    line_no: int; line: str; reason: str

# parrot/outputs/a2ui/graph/layout.py
def compute_positions(spec: GraphSpec, *, rank_sep: float = 80.0, node_sep: float = 40.0) -> LayoutResult: ...
    # Pure, deterministic. Longest-path layering over the (cycle-broken) DAG; barycentre
    # ordering, 4 sweeps; coordinate assignment honouring `direction`; group boxes.
    # Raises GraphTooLargeError(len(nodes)) when len(spec.nodes) > MAX_STATIC_NODES.

# parrot/outputs/a2ui/builders.py
def build_graph(
    *,
    nodes: Sequence[GraphNode | dict[str, Any]],
    edges: Sequence[GraphEdge | dict[str, Any]],
    kind: GraphKind = "flowchart",
    direction: Direction = "TB",
    title: str | None = None,
    accessible_description: str | None = None,
    size: VizSize = "tile",
    groups: Sequence[GraphGroup | dict[str, Any]] | None = None,
    layout: GraphLayout | dict[str, Any] | None = None,
    selection: GraphSelection | dict[str, Any] | None = None,
    data_binding: str | None = None,          # "/nodes" → data={"path": "/nodes"}
    data_model: dict[str, Any] | None = None,
    action: Action | None = None,             # TOOL origin only (existing D10b gate)
    compute_layout: bool = True,              # fill layout.positions when engine == "layered" and absent
    surface_id: str = "graph",
    origin: ProducerOrigin = ProducerOrigin.TOOL,
) -> CreateSurface: ...
    # Surface catalogId stays DEFAULT_CATALOG_ID (every public builder does this); the Graph component
    # carries catalogId=VIZ_CORE_CATALOG_ID explicitly.

# parrot/outputs/a2ui/adapters/flow.py  (NEW — no parrot.bots import; G8 preserved)
def flow_definition_to_graph(
    definition: Mapping[str, Any],            # FlowDefinition.model_dump(by_alias=True) shape
    *,
    kind: GraphKind = "flowchart",
    direction: Direction = "TB",
    data_binding: str | None = None,
) -> GraphSpec: ...
    # nodes[].type → shape table (§2 Overview); edges[].condition/predicate → label/kind;
    # `to: list` → one GraphEdge per target; node `label` defaults to `id`;
    # accessible_description defaults to "<flow> workflow: N steps, M transitions".

# packages/ai-parrot-visualizations/.../a2ui_renderers/_intercept.py  (NEW, satellite-internal helper)
def resolve_component_catalog(comp: Component, surface_catalog_id: str | None) -> str   # thin wrapper over catalog.resolve_catalog
def intercepts(table: frozenset[tuple[str, str]], comp: Component, surface_catalog_id: str | None) -> bool
```

```svelte
<!-- ui/src/lib/components/agents/canvas/a2ui/A2UIGraph.svelte (NEW) -->
<!-- props: properties (baked Graph props incl. layout.positions), dataModel, onNodeClick?(nodeId) -->
<!-- Renders ECharts `graph` series with layout:'none' from positions (fallback 'circular'
     when absent); node itemStyle from STATE_TO_STATUS role → Tailwind token; groups as
     ECharts markArea/graphic boxes; edge lineStyle.type from kind; arrows on; tooltip from
     meta; `size` → container class (inline/tile/hero); aria-label = accessibleDescription. -->
```

---

## 3. Module Breakdown

### Module 0: viz-core catalog shell
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/viz_core/__init__.py` (new),
  `catalog/viz_core/spec/catalog.json` (vendored copy of `sdd/proposals/assets/a2ui-viz-core/viz-core.catalog.json`),
  `catalog/__init__.py`, `catalog/export.py`, `producer.py`,
  `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_intercept.py` (new),
  `ui/.../canvas/a2ui/a2ui-types.ts`
- **Responsibility**: `VIZ_CORE_CATALOG_ID`, `VIZ_CORE_INSTRUCTIONS`; `_CATALOG` keyed by
  `(catalog_id, name)` with `register_component` writing the pair and rejecting a duplicate
  pair (a same-name registration in a *different* catalog is allowed); `get_component(name,
  catalog_id=None)` unique-or-ambiguous semantics; `list_components(catalog_id)`;
  `catalog_instructions(catalog_ids)` + `catalog_header_instructions`; `_component_exists`
  and the gate lookup at `catalog/__init__.py:498` using the keyed registry with the
  resolved catalog id; `export_catalog_definition` emitting scoped instructions;
  `write_catalog_definition(catalog_id=…)`; the producer passing catalog ids; the satellite
  `intercepts()` helper; the `VIZ_CORE_CATALOG_ID` TS constant. No component is registered
  here except through Module 2.
- **Depends on**: nothing new. Must land first.

### Module 1: Graph vocabulary — `graph/models.py`
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/graph/__init__.py`, `graph/models.py`
- **Responsibility**: `GraphSpec` family with camelCase aliases, `accessible_description`,
  `size`, and the model-level validators listed in §2 Data Models; `GraphTooLargeError`;
  package exports.
- **Depends on**: `pydantic` only.

### Module 2: Catalog composite — `catalog/viz_core/graph.py`
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/viz_core/graph.py`, `catalog/viz_core/__init__.py` (registration import)
- **Responsibility**: `GRAPH_SCHEMA = derive_schema(GraphSpec, binding_fields=("data",),
  required=("nodes", "edges"))` **plus** an explicit `action` property (`$ref` to the
  vendored `common_types.json#/$defs/Action`) merged after derivation; `GRAPH_INSTRUCTIONS`
  (LLM-facing: when to use, node/edge fields, shapes, states, "always give
  `accessibleDescription`", "bind `data` for live state, never inline positions, never
  set `action`"); `@register_component("Graph", catalog_id=VIZ_CORE_CATALOG_ID) class
  GraphComponent` with `lower()` per §2 Data Models. Golden `graph_lowered.json`.
- **Depends on**: Modules 0, 1, 3 (`to_mermaid` for the `graph-source` Text).

### Module 3: Mermaid codec — `graph/mermaid.py`
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py`
- **Responsibility**: hand-written tokenizer/parser for the three dialects; `to_mermaid`
  canonical emitter; `MermaidCodecError`. Shape mapping: `[x]` rect, `(x)` rounded, `{x}`
  diamond, `((x))` circle, `{{x}}` hexagon, `[[x]]` subroutine. Edge mapping: `-->` solid,
  `-.->` dashed, `==>` thick; labels via `-- text -->` and `-->|text|`. `subgraph id [label]
  … end` ↔ groups. State: `[*] --> A` (synthetic `__start__`/`__end__` circle nodes),
  `A --> B : label`, `state "label" as id`, composite `state X { … }` ↔ group. Sequence:
  `participant A as Label`, `A->>B: msg` solid / `A-->>B: msg` dashed, ordered edges with
  `meta.seq`. Comments `%%` ignored. Anything else → `MermaidCodecError`.
  `accessible_description` and `size` are not representable in mermaid and are dropped on
  export, left `None`/default on import (round-trip tests compare modulo those two fields).
- **Depends on**: Module 1.

### Module 4: Layered layout — `graph/layout.py`
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/graph/layout.py`
- **Responsibility**: `compute_positions`, `LayoutResult`, `MAX_STATIC_NODES`; cycle
  breaking by DFS back-edge reversal (recorded in `reversed_edges`); `networkx` may be used
  for `topological_generations`/`find_cycle` only; group bounding boxes; `direction`
  handling by axis swap/mirror. Deterministic ordering (stable sort on input order).
- **Depends on**: Module 1; `networkx` (core hard dep, verified §6).

### Module 5: Builder + flow adapter
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py`, `adapters/flow.py`, `adapters/__init__.py`
- **Responsibility**: `build_graph` (fills positions via Module 4 when `compute_layout`
  and engine layered and positions absent; `data_binding`/`data_model`; `action` passes
  through `build_surface(origin=...)`; sets the component's `catalogId` to viz-core);
  `flow_definition_to_graph` per §2; `__all__`.
- **Depends on**: Modules 0, 1, 2, 4.

### Module 6: Satellite renderers — SVG, ECharts, interactive-HTML, SSR/PDF
- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_graph_svg.py` (new), `echarts.py`, `interactive_html.py`, `ssr_html.py`, `pdf.py`
- **Responsibility**: `_graph_svg.render_graph_svg(props, *, theme) -> str` (uses
  `compute_positions` when `layout.positions` absent; shapes, arrowheads, labels, group
  boxes, `STATE_TO_STATUS` → `DesignSystem` token fill, `<title>` from
  `accessibleDescription`, per-node `<title>` from `meta`, `data-state`/`data-status`
  attributes, `size` → viewBox aspect class); `EChartsRenderer._build_graph_option`,
  `supported_components |= {"Graph"}`, `supported_catalog_ids += [VIZ_CORE_CATALOG_ID]`;
  `interactive_html._INTERCEPTED` converted to `(catalog_id, name)` pairs (existing five
  entries under `DEFAULT_CATALOG_ID`) + `(VIZ_CORE_CATALOG_ID, "Graph")`, `_render_graph`
  embedding the SVG plus a collapsed `<details>` with the mermaid source;
  `ssr_html._lower_composites` intercepts `(viz-core, "Graph")` → SVG (PDF inherits);
  degradation records for `engine: force` (→ layered), for `GraphTooLargeError` (→ lowered
  edge list, truncated to `MAX_STATIC_NODES` rows), and for a viz-core component on a
  renderer whose `supported_catalog_ids` lacks viz-core (→ lowering + record naming the
  catalog id).
- **Depends on**: Modules 0, 1, 3, 4.

### Module 7: Bundled UI — `A2UIGraph.svelte`
- **Path**: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIGraph.svelte` (new), `A2UINode.svelte`, `a2ui-types.ts`, `A2UIGraph.test.ts` (new)
- **Responsibility**: `A2UINode.svelte` resolves the component's catalog id (own
  `catalogId`, else surface default) and dispatches `Graph` only for viz-core; ECharts
  `graph` series on `visualizations/ECharts.svelte`; positions from props (fallback
  `circular`); `STATE_TO_STATUS` → existing Tailwind tokens; groups as boxes;
  `selection.selected` highlighted; `size` → container class; `aria-label` from
  `accessibleDescription`; node click calls an optional `onNodeClick` prop (wired to
  action dispatch by `a2ui-live-workflow-surface`; no-op here). Vitest coverage for option
  building and catalog-aware dispatch.
- **Depends on**: Module 2 (wire shape); `features.a2ui` flag already present.

### Module 8: Docs + conformance
- **Path**: `docs/outputs/a2ui-v1.md`, `docs/frontend/agentdashboard-a2ui-reference.md`,
  `tests/outputs/a2ui/conformance/test_all_emitters.py`, `tests/outputs/a2ui/test_catalog_parity.py`
- **Responsibility**: "Two catalogs" section becomes "Three catalogs, one resolution
  rule" with the viz-core principles (what-not-how, semantic roles/formats, size intent,
  `accessibleDescription`, standard `action`); `Graph` section (schema, lowering,
  `parrot_role` additions `description`, `edge`, `edge-list`, `graph-source`;
  `parrot_variant: graph`; renderer matrix row; state → status role table; action click
  contract; mermaid codec subset); frontend reference §5 gains a "5.4 viz-core catalog"
  subsection with `Graph` as its first entry (Parrot composites count stays 10);
  `test_build_graph` conformance; parity test that `GRAPH_SCHEMA` has every `GraphSpec`
  field plus `action`; `catalog_definition.json` for viz-core written to
  `catalog/viz_core/spec/catalog_definition.json` by the existing export test helper.
- **Depends on**: Modules 0, 2, 5, 6, 7.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_registry_keyed_by_catalog_and_name` | 0 | registering `("X", DEFAULT)` and `("X", VIZ_CORE)` both succeed; `get_component("X")` raises `CatalogError` (ambiguous) with both ids; `get_component("X", VIZ_CORE_CATALOG_ID)` returns the viz-core one |
| `test_registry_rejects_duplicate_pair` | 0 | registering the same `(catalog_id, name)` twice → `CatalogError` (today's behaviour preserved) |
| `test_bare_name_lookup_stays_unique_today` | 0 | for every registered name, `get_component(name)` succeeds — pins that no name is duplicated until the charts spec |
| `test_component_exists_third_catalog` | 0 | `_component_exists("Graph", VIZ_CORE_CATALOG_ID)` True; `_component_exists("Graph", DEFAULT_CATALOG_ID)` False; `_component_exists("Text", VIZ_CORE_CATALOG_ID)` False (viz-core does not `$ref` Basic) |
| `test_catalog_instructions_scoped` | 0 | `catalog_instructions([VIZ_CORE_CATALOG_ID])` starts with `VIZ_CORE_INSTRUCTIONS` and lists only viz-core components; `catalog_instructions()` (None) equals today's aggregate plus the header |
| `test_export_viz_core_catalog_validates` | 0 | `export_catalog_definition(catalog_id=VIZ_CORE_CATALOG_ID)` validates against vendored `catalog_definition.json`; `components` contains `Graph` and (with `include_basic=True`) the Basic `$ref`s; `instructions` is the scoped block |
| `test_write_catalog_definition_catalog_id` | 0 | writes the viz-core document to a tmp path |
| `test_producer_passes_surface_catalogs` | 0 | producer system prompt for a viz-core surface contains the viz-core header and not the Parrot `Chart` line |
| `test_intercepts_resolves_catalog` | 0/6 | Parrot `Chart` with no `catalogId` in a Parrot-default surface intercepts under `(DEFAULT, "Chart")`; a `Graph` with `catalogId: viz-core` intercepts under `(VIZ_CORE, "Graph")`; a `Graph` without `catalogId` in a Parrot-default surface does NOT intercept (and fails validation as unknown) |
| `test_graphspec_rejects_dangling_edge` | 1 | edge to unknown node → `ValidationError` |
| `test_graphspec_rejects_duplicate_node_ids` | 1 | duplicate id → `ValidationError` |
| `test_graphspec_dag_rejects_cycle` | 1 | `kind="dag"` with A→B→A → `ValidationError`; `kind="flowchart"` accepts it |
| `test_graphspec_manual_requires_positions` | 1 | `engine="manual"` without full positions → `ValidationError` |
| `test_graphspec_size_and_description` | 1 | `size` defaults `tile`, rejects `"320px"`; `accessibleDescription` alias round-trips |
| `test_graph_schema_has_all_spec_fields` | 2 | every `GraphSpec` alias is a `GRAPH_SCHEMA` property; `data` is the binding descriptor; `action` present as the `Action` `$ref` (mirrors `test_derived_chart_schema_has_all_config_fields`) |
| `test_graph_schema_has_no_colour_vocabulary` | 2 | no property name or enum value in `GRAPH_SCHEMA` matches `color|colour|palette|hex|font|px|width|height` (G9) |
| `test_graph_registered_under_viz_core` | 2 | `get_component("Graph", VIZ_CORE_CATALOG_ID).definition` → `catalog_id == VIZ_CORE_CATALOG_ID`, `requires_actions=False`, `tool_only=False`, `allowed_parents=None`; `get_component("Graph")` also resolves (unique) |
| `test_graph_lower_golden` | 2 | lowered tree == `golden/graph_lowered.json`; validates via `validate_envelope`; first child is the `description` Text |
| `test_graph_lower_generates_description_when_absent` | 2 | no `accessibleDescription` → `"Graph of 3 nodes and 2 edges (flowchart)"` |
| `test_graph_lower_passes_data_binding_through` | 2 | `data={"path": "/nodes"}` → `parrot_graph_data` on the edge-list Column, unresolved |
| `test_graph_llm_origin_rejects_action` | 2 | `Graph` with `action` under `ProducerOrigin.LLM` → `ACTION_NOT_ALLOWED_FOR_LLM`; `TOOL` accepts |
| `test_graph_in_infographic_section_lowers` | 2 | `{"component": "Graph", "catalogId": VIZ_CORE, "properties": {...}}` inside an `Infographic` section lowers recursively |
| `test_mermaid_roundtrip_flowchart` | 3 | `from_mermaid(to_mermaid(spec)) == spec` (modulo `accessibleDescription`/`size`) for flowchart with all 6 shapes, 3 edge kinds, labels both syntaxes, a subgraph |
| `test_mermaid_roundtrip_state` | 3 | `[*]` start/end, `: label`, `state "x" as y`, composite state → group |
| `test_mermaid_roundtrip_sequence` | 3 | participants with aliases, solid/dashed messages, `meta.seq` order preserved |
| `test_mermaid_quotes_reserved_labels` | 3 | label with `[`, `|`, `"` emitted quoted and parsed back identically |
| `test_mermaid_rejects_unsupported_construct` | 3 | `classDef`, `click`, `style`, `%%{init}`, `loop` → `MermaidCodecError` with correct `line_no` |
| `test_mermaid_ignores_comments_and_blank_lines` | 3 | `%%` lines skipped |
| `test_mermaid_error_is_catalog_validation_error` | 3 | `isinstance(MermaidCodecError(...), CatalogValidationError)` |
| `test_layout_ranks_follow_edges` | 4 | for every non-reversed edge, `rank(to) > rank(from)` |
| `test_layout_deterministic` | 4 | two calls → identical `LayoutResult` |
| `test_layout_breaks_cycles` | 4 | cyclic flowchart → `reversed_edges` non-empty, all nodes positioned |
| `test_layout_direction_lr_swaps_axes` | 4 | `LR` positions == transposed `TB` positions |
| `test_layout_group_boxes_contain_members` | 4 | every member inside its group box |
| `test_layout_too_large_raises` | 4 | `MAX_STATIC_NODES + 1` nodes → `GraphTooLargeError` |
| `test_build_graph_fills_positions` | 5 | default `compute_layout` → `layout.positions` covers all nodes; `compute_layout=False` leaves it absent |
| `test_build_graph_sets_viz_core_catalog_id` | 5 | the `Graph` component carries `catalogId == VIZ_CORE_CATALOG_ID`; the surface `catalogId` stays `DEFAULT_CATALOG_ID` |
| `test_build_graph_action_tool_origin_only` | 5 | `action=` with default TOOL origin OK; `origin=LLM` raises `CatalogValidationError` |
| `test_flow_definition_to_graph_shapes_and_edges` | 5 | start/end → circle, decision → diamond, tool → subroutine; `to: list` → N edges; `on_error` → dashed; `on_condition` label == predicate; default `accessibleDescription` generated |
| `test_adapters_flow_has_no_bots_import` | 5 | covered by existing `adapters/test_import_rule.py` (no change) — asserted still green |
| `test_graph_svg_uses_status_tokens` | 6 | SVG contains one shape per node; `state="failed"` node has `data-status="critical"` and a fill referencing `--accent-red`; `state="completed"` → `good`/`--accent-green`; no literal hex in the SVG |
| `test_graph_svg_title_from_description` | 6 | `<svg><title>` equals `accessibleDescription` |
| `test_graph_svg_arrowheads_and_edge_kinds` | 6 | `dashed` → `stroke-dasharray`; `thick` → larger `stroke-width`; marker-end present |
| `test_echarts_graph_option` | 6 | `series[0].type == "graph"`, `layout == "none"`, `data[i].x/y` from positions, `links` count == edges |
| `test_echarts_capabilities_include_viz_core` | 6 | `get_a2ui_renderer("echarts").capabilities.supported_catalog_ids` contains `VIZ_CORE_CATALOG_ID` (same for interactive-html, ssr_html, pdf; NOT adaptive_cards/folium) |
| `test_interactive_html_intercepts_graph` | 6 | output contains `<svg` and a `<details>` with the mermaid source; no degradation record |
| `test_ssr_force_layout_degrades_to_layered` | 6 | `engine="force"` → SVG rendered + `degraded[]` entry naming force |
| `test_ssr_graph_too_large_degrades` | 6 | > cap → lowered edge list + `degraded[]` entry |
| `test_adaptive_cards_degrades_unsupported_catalog` | 6 | viz-core `Graph` on adaptive_cards → lowered tree rendered + `degraded[]` entry naming `VIZ_CORE_CATALOG_ID` |
| `test_pdf_graph_renders_svg` | 6 | PDF lane's pre-render HTML contains the graph SVG |
| `A2UIGraph.test.ts: builds echarts option from positions` | 7 | nodes carry x/y; links from edges; state → status role → token class |
| `A2UIGraph.test.ts: falls back to circular without positions` | 7 | `layout === 'circular'` |
| `A2UINode.test.ts: dispatches viz-core Graph` | 7 | `{component: 'Graph', catalogId: VIZ_CORE}` renders `A2UIGraph`; `{component: 'Graph'}` with a Parrot surface default renders the unsupported placeholder |

### Integration Tests
| Test | Description |
|---|---|
| `test_build_graph` (conformance/test_all_emitters.py) | `build_graph(...)` envelope validates against vendored `agent_to_renderer.json`; lowered tree validates under `ProducerOrigin.LLM` |
| `test_flow_to_graph_to_mermaid_roundtrip` | dev-loop `FlowDefinition` fixture (mapping) → `flow_definition_to_graph` → `build_graph` → `to_mermaid` → `from_mermaid` equals the adapter's spec modulo positions, `accessibleDescription`, `size` |
| `test_graph_renders_on_every_registered_renderer` | for each `register_a2ui_renderer` name: render a `Graph` envelope; native lanes have no `Graph` degradation record, others have exactly one record and a lowered `description` + `graph-source` Text |
| `test_catalog_definition_includes_graph` | `export_catalog_definition(catalog_id=VIZ_CORE_CATALOG_ID)["components"]["Graph"]` present with the derived schema; the Parrot export (`DEFAULT_CATALOG_ID`) does NOT contain `Graph` |
| `test_mixed_catalog_surface_validates` | the shape of `sdd/proposals/assets/a2ui-viz-core/viz-core.example.jsonl` line 1 with `Stat`/`Chart`/`Series` replaced by one viz-core `Graph` and a Basic `Column` root validates; the same with the `Graph` lacking `catalogId` fails with `UNKNOWN_COMPONENT` |
| `test_frontend_guide_graph_example_validates` | the `Graph` example added to `docs/frontend/agentdashboard-a2ui-reference.md` validates (extends `tests/integration/test_frontend_guide_examples.py`) |

### Test Data / Fixtures
```python
@pytest.fixture
def dev_loop_flow_mapping() -> dict:
    """FlowDefinition.model_dump(by_alias=True) of a 7-node flow: start → research →
    (decision) → development → qa → close → end, with an on_error edge to failure_handler
    and a fan-out `to: [qa, docs]`. Stored as tests/outputs/a2ui/fixtures/dev_loop_flow.json
    so the a2ui tests never import parrot.bots."""

@pytest.fixture
def mermaid_samples() -> dict[str, str]:
    """Canonical flowchart / stateDiagram-v2 / sequenceDiagram texts and their expected
    GraphSpec JSON (tests/outputs/a2ui/fixtures/mermaid/*.mmd + *.json)."""

@pytest.fixture
def viz_core_example_envelope() -> dict:
    """sdd/proposals/assets/a2ui-viz-core/viz-core.example.jsonl line 1, loaded verbatim (mixed-catalog shape reference)."""

GOLDEN_DIR / "graph_lowered.json"   # regenerated by the golden helper used in test_components_*.py
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC-0 The viz-core shell exists: `VIZ_CORE_CATALOG_ID`/`VIZ_CORE_INSTRUCTIONS` in `catalog/viz_core/`; `_CATALOG` keyed by `(catalog_id, name)`; `get_component(name, catalog_id=None)` unique-or-ambiguous; `list_components`/`catalog_instructions` scoped; `export_catalog_definition(catalog_id=VIZ_CORE_CATALOG_ID)` validates against the vendored `catalog_definition.json`; the producer passes surface catalog ids; every existing bare-name call site still passes its tests unchanged (G0).
- [ ] AC-1 `Graph` is registered under `VIZ_CORE_CATALOG_ID` with `requires_actions=False`, `tool_only=False`, no `allowed_parents`; `GRAPH_SCHEMA` is derived from `GraphSpec`, contains every spec field including `accessibleDescription` and `size`, `data` as the binding descriptor, and `action` as the `Action` `$ref`; the Parrot catalog export does not contain `Graph` (G1).
- [ ] AC-2 `GraphSpec` rejects dangling edges, duplicate ids, cycles when `kind="dag"`, `manual` layout without full positions, and non-enum `size` values (G1).
- [ ] AC-3 `lower()` emits Basic primitives only: `Card{Column[description, title?, caption, edge-list, graph-source]}` with `parrot_variant: graph`; the description is `accessibleDescription` or a generated summary; golden `graph_lowered.json` pinned; `data` binding passes through under `parrot_graph_data` (G1, G2, G8).
- [ ] AC-4 A `Graph` carrying `action` validates under `ProducerOrigin.TOOL` and is rejected under `ProducerOrigin.LLM` by the existing gate; no new gate code; no `selectAction` anywhere (G3).
- [ ] AC-5 `to_mermaid`/`from_mermaid` round-trip for flowchart (6 shapes, 3 edge kinds, both label syntaxes, subgraph), stateDiagram-v2 and sequenceDiagram fixtures (modulo `accessibleDescription`/`size`); unsupported constructs raise `MermaidCodecError` with the right line number; `MermaidCodecError` is a `CatalogValidationError` (G4).
- [ ] AC-6 `compute_positions` is deterministic, positions every node, respects edge direction on non-reversed edges, handles cycles, honours all four `direction` values, boxes groups, and raises `GraphTooLargeError` above `MAX_STATIC_NODES` (G5).
- [ ] AC-7 `build_graph` fills `layout.positions` by default, sets the component `catalogId` to viz-core while the surface default stays Parrot, validates through `build_surface`, is listed in `builders.__all__` and covered by the conformance suite against the vendored v1.0 schema (G6, G9).
- [ ] AC-8 `flow_definition_to_graph` maps the dev-loop fixture with the §2 shape/condition rules, generates a default `accessibleDescription`, and `adapters/test_import_rule.py` stays green unchanged (G6, G9).
- [ ] AC-9 ECharts renderer declares viz-core in `supported_catalog_ids`, emits a `graph` series with `layout: "none"` and positions; `supported_components` includes `Graph` (G7).
- [ ] AC-10 interactive-HTML, SSR-HTML and PDF declare viz-core, intercept `(viz-core, "Graph")` via the catalog-aware helper, and embed an inline SVG whose node fills come from `STATE_TO_STATUS` roles resolved to `DesignSystem` tokens (no literal hex), with `<title>` from `accessibleDescription`; `engine: force` and oversize graphs degrade with a recorded `degraded` entry; Adaptive Cards and Folium show the lowered description + edge list + mermaid source with a `degraded` entry naming the catalog (G7, G8).
- [ ] AC-11 Bundled UI dispatches `Graph` only when the component resolves to viz-core and renders it via `A2UIGraph.svelte` behind `features.a2ui`; vitest suites for option building and catalog-aware dispatch pass (G7).
- [ ] AC-12 `docs/outputs/a2ui-v1.md` documents three catalogs and the viz-core principles; both docs document `Graph` (schema, lowering, click contract, state → status table, mermaid subset, renderer row); the reference's `Graph` example validates in `test_frontend_guide_examples.py` (G0, G7).
- [ ] AC-13 `test_no_exec.py`, `adapters/test_import_rule.py`, `catalog/test_spec_vendored.py` and every existing golden remain green; no existing envelope shape changes; `GRAPH_SCHEMA` contains no colour/font/pixel/library vocabulary (G9).
- [ ] AC-14 `pytest packages/ai-parrot/tests/outputs/a2ui packages/ai-parrot-visualizations/tests -q` passes; `ruff check` clean on touched files; `npm test` in `packages/ai-parrot-server/ui` passes.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> All paths are relative to the repo root; core source is `packages/ai-parrot/src/parrot/`,
> visualizations satellite is `packages/ai-parrot-visualizations/src/parrot/`.
> Re-verified 2026-09-05 on `dev` (d9e8dca7a) for v0.2.

### Verified Imports
```python
from parrot.outputs.a2ui.catalog import register_component, get_component, list_components, catalog_instructions, resolve_catalog, validate_envelope   # catalog/__init__.py:107, :181, :190, :219, :233, :392
from parrot.outputs.a2ui.catalog.base import (                                                # catalog/base.py
    BasicNode, BasicTree, TabSpec, to_components,                                             # :101, :145, :164
    ComponentDefinition, ProducerOrigin,                                                      # :224, :89
    CatalogError, ComponentContractError, CatalogValidationError,                             # :295, :299, :307
    DEFAULT_CATALOG_ID, ACTION_NOT_ALLOWED_FOR_LLM, TOOL_ONLY_NOT_ALLOWED_FOR_LLM,             # :53, :78, :86
)
from parrot.outputs.a2ui.catalog.basic import BASIC_CATALOG_ID, load_spec, basic_components   # catalog/basic/__init__.py:44, :90, :205
from parrot.outputs.a2ui.catalog.parrot._derive import derive_schema                          # catalog/parrot/_derive.py:88
from parrot.outputs.a2ui.models import (                                                      # models.py
    Component, CreateSurface, DataBinding, ChildTemplate, Action, Extensions, ComponentMetadata, UpdateDataModel,  # :400, (CreateSurface), :155, :212, :250, :341, :364, :490
)
from parrot.outputs.a2ui.builders import build_surface, build_chart, build_kpicard            # builders.py:50, :97, :118
from parrot.outputs.a2ui.baking import bake_envelope, persist_envelope                        # baking.py:356, :399
from parrot.outputs.a2ui.renderers import (                                                   # renderers/__init__.py
    RendererCapabilities, AbstractA2UIRenderer, register_a2ui_renderer, get_a2ui_renderer,    # :51, :78, :108, :141
)
from parrot.outputs.a2ui.renderers.degrade import degrade, degradation_record                 # renderers/degrade.py:24, :46
from parrot.outputs.a2ui.catalog.export import export_catalog_definition, write_catalog_definition  # catalog/export.py:215, :299
from parrot.outputs.a2ui.adapters import infographic_response_to_envelope                     # adapters/infographic.py:599 (re-exported in adapters/__init__.py)
from parrot.outputs.a2ui.adapters.structured import chart_to_surface                          # adapters/structured.py:176
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition, EdgeDefinition  # definition.py:377, :155, :246 — TESTS/CALLERS ONLY, never from parrot.outputs.a2ui
import networkx                                                                               # core hard dep, packages/ai-parrot/pyproject.toml:170
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py
_CATALOG: dict[str, RegisteredComponent] = {}   # line 95 — keyed by BARE NAME today; Module 0 rekeys to (catalog_id, name)
_STRUCTURED_INLINE_DATA_COMPONENTS = frozenset({"Chart", "DataTable", "Map"})   # line 104 — Graph is NOT added
def register_component(name: str, *, requires_actions: bool = False, catalog_id: str = DEFAULT_CATALOG_ID,
                       is_primitive: bool = False, allowed_parents: list[str] | None = None,
                       allowed_children: list[str] | None = None, tool_only: bool = False) -> Callable[[type], type]  # :107-116
def get_component(name: str) -> RegisteredComponent   # :181 — bare name; 7 external call sites:
#   adapters/structured.py (1), catalog/parrot/infographic.py (1), catalog/parrot/report.py (1),
#   a2ui_renderers/adaptive_cards.py (1), interactive_html.py (2), ssr_html.py (1)
def list_components() -> list[ComponentDefinition]    # :190
def catalog_instructions() -> str                     # :219-230 — "<name>: <instructions>" for EVERY registered component, name-sorted, unscoped
def resolve_catalog(component_catalog_id: str | None, surface_catalog_id: str | None) -> str   # :233-256 — component wins, else surface, else CATALOG_UNRESOLVED
def _component_exists(name: str, resolved_catalog_id: str) -> bool   # :266-294 — :286 basic JSON, :288 parrot (+basic), :293 any other id via entry.definition.catalog_id
def validate_envelope(envelope: CreateSurface | UpdateComponents, *, origin: ProducerOrigin = ProducerOrigin.TOOL,
                      surface_catalog_id: str | None = None) -> None   # :392-397; :438 effective surface id; :481 resolve per component;
#   :498 `entry_for_gate = _CATALOG.get(comp.component)` (bare name — Module 0 changes to keyed lookup);
#   :499-502 `is_action_bearing = comp.action is not None or entry.definition.requires_actions` — the ONLY action check (no nested props)
#   :515 tool_only gate

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py
DEFAULT_CATALOG_ID = "https://parrot.dev/catalogs/v1"   # :53
class BasicNode(BaseModel):                     # :101
    id: str | None = None; component: str; child: BasicNode | None; children: list[BasicNode] | ChildTemplate | None
    template_source: BasicNode | None; tabs: list[TabSpec] | None; metadata: ComponentMetadata | None   # :136-142
def to_components(tree: BasicNode, *, id_prefix: str = "blk") -> list[Component]   # :164
class ComponentDefinition(BaseModel):           # :224
    name; catalog_id: str = DEFAULT_CATALOG_ID (:249); schema_ (alias "schema"); instructions; requires_actions; is_primitive; allowed_parents; allowed_children; tool_only  # :248-256

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/__init__.py
BASIC_CATALOG_ID = "https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json"   # :44
def load_spec(name: SpecName) -> dict   # :90 — names: agent_capabilities, agent_to_renderer, catalog, catalog_definition, common_types, renderer_to_agent
def basic_components() -> list          # :205
# catalog/basic/spec/common_types.json#/$defs: ComponentId, CallId, AccessibilityAttributes, Extensions, ComponentCommon
#   (properties: id, catalogId, accessibility, metadata — NO `action`), Child, ChildList, DataBinding, DynamicValue,
#   DynamicString, DynamicNumber, DynamicBoolean, DynamicStringList, FunctionCommon, IndexSystemFunction, FunctionCall,
#   CheckRule, Checkable, Action, Surface, FunctionResponse
# catalog/basic/spec/catalog.json top-level keys: $schema, $id, protocolVersion, title, description, catalogId, instructions,
#   components (18), functions, $defs{anyComponent, anyFunction} — the SAME shape as artifacts/a2ui/viz-core.catalog.json

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/export.py
def export_catalog_definition(*, catalog_id: str = DEFAULT_CATALOG_ID, include_basic: bool = True,
                              executor: FunctionExecutor | None = None) -> dict[str, Any]   # :215-297
#   filters `definition.catalog_id != catalog_id or definition.is_primitive` (:261) — a viz-core export already works
#   once components are registered under that id; `"instructions": catalog_instructions()` (:293) is UNscoped today
def write_catalog_definition(path: Path) -> None   # :299 — no catalog_id parameter today

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/_derive.py
def derive_schema(model: type[BaseModel], *, binding_fields: Sequence[str], required: Sequence[str] = ()) -> dict[str, Any]   # :88-93
# strips Pydantic `title` annotations, keeps $defs, camelCases any snake_case top-level property

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/chart.py  (pattern to copy — stays in the PARROT catalog, untouched)
CHART_SCHEMA = derive_schema(StructuredChartConfig, binding_fields=("data",), required=("type", "x", "y"))
@register_component("Chart") class ChartComponent: SCHEMA; INSTRUCTIONS; def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree
# binding pass-through convention: extensions["parrot_series_data"] = props["data"]

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/__init__.py — registration imports (chart, datatable, filterbar,
#   htmldocument, infocard, infographic, kpicard, map, report, timeline); `form` deliberately excluded

# packages/ai-parrot/src/parrot/outputs/a2ui/producer.py
#   :211 `instructions = catalog_instructions()` appended to the system prompt; :243 `validate_envelope(envelope, origin=LLM, surface_catalog_id=catalog)`

# packages/ai-parrot/src/parrot/outputs/a2ui/builders.py
__all__ = ["build_card", "build_chart", "build_datatable", "build_html_document", "build_infographic", "build_kpicard", "build_map", "build_surface"]  # :31-40
_ROOT_COMPONENT_ID = "root"   # :44
def build_surface(component: str, properties: dict[str, Any], *, surface_id: str, component_id: str = _ROOT_COMPONENT_ID,
                  data_model: dict[str, Any] | None = None, origin: ProducerOrigin = ProducerOrigin.LLM,
                  metadata: ComponentMetadata | None = None) -> CreateSurface   # :50-59 — surface catalogId = DEFAULT_CATALOG_ID

# packages/ai-parrot/src/parrot/outputs/a2ui/models.py
class ChildTemplate(BaseModel): component_id: str = Field(alias="componentId"); path: str   # :212-224
class Component(BaseModel):   # :400 — id, component, catalog_id (alias catalogId, :431), child, children: ChildList | None (:433), weight, accessibility, checks, action: Action | None, metadata; extra="allow" (props top-level)
class DataBinding(BaseModel): path: str    # :155
class Action(BaseModel): event | function_call   # :250
class Extensions(RootModel[dict[str, Any]])      # :341 — official-prefix keys rejected; parrot_* allowed
class ComponentMetadata(BaseModel): extensions: Extensions | None   # :364, :373

# packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py
class RendererCapabilities(BaseModel): interactive: bool; supports_actions: bool; supports_updates: bool; output: str;
    supported_catalog_ids: list[str] = Field(default_factory=lambda: [BASIC_CATALOG_ID, DEFAULT_CATALOG_ID])   # :74
    supported_components: set[str] = Field(default_factory=set)   # :75 — bare names
def register_a2ui_renderer(name: str, capabilities: RendererCapabilities)   # :108

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py
_INTERCEPTED = {"Chart", "DataTable", "Infographic", "Map", "HtmlDocument"}   # :120 — bare names; Module 6 converts to (catalog_id, name)
class InteractiveHTMLRenderer:  async def render(self, envelope: CreateSurface, *, bake: bool = True) -> RenderedArtifact  # :606
    capabilities supported_components at :562
    def _lower_composites(self, envelope: CreateSurface) -> CreateSurface   # :666 — skips _INTERCEPTED
    def _render_chart(self, props: dict[str, Any], degradations: list[dict[str, Any]]) -> str   # :1024 (pattern for _render_graph)
    def _render_htmldocument(self, props: dict[str, Any]) -> str   # :1205

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py
_UNSUPPORTED_CHART_TYPES = frozenset({"gauge", "funnel", "waterfall", "heatmap", "treemap"})   # :84
class SSRHTMLRenderer: registered :118, supported_components :129; _lower_composites(...) intercept pattern at :276 (`if comp.component == "Chart"`), degradations list appended via degradation_record
class PDFRenderer(SSRHTMLRenderer)   # pdf.py:99; capabilities :96 (SSR minus Video/AudioPlayer); def _chart_svg(props: dict) -> str at pdf.py:50 (bar-only; untouched by this spec)

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py
_SERIES_TYPE = {...}   # :41 ; _ROW_NATIVE_TYPES :59
@register_a2ui_renderer(_SURFACE_NAME, RendererCapabilities(interactive=False, supports_actions=False, supports_updates=False,
    output="application/json", supported_components={"Chart"}))   # :62-70 (supported_components :68)
class EChartsRenderer(AbstractA2UIRenderer): async def render(...); def _build_option(self, props: dict[str, Any]) -> dict[str, Any]  # :128
# adaptive_cards.py:218 and folium_map.py:269 — supported_components sets; default supported_catalog_ids (no viz-core)

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/assets/design_system/__init__.py
class DesignSystem:   # :79
    @classmethod def stylesheet(cls, theme: str | ThemeConfig | None = None, layout: str | None = None) -> str   # :95
    @classmethod def resolve(cls, envelope: CreateSurface, *, theme_default: str | None = None, layout_default: str | None = None) -> tuple[str, str]  # :131
# CSS tokens available in base.css/components.css: --accent-green, --accent-amber, --accent-red, --accent-teal, --neutral-muted, --primary, --primary-dark, --on-primary, --callout-*

# packages/ai-parrot/src/parrot/bots/flows/flow/definition.py  (READ BY TESTS/CALLERS ONLY)
class NodeDefinition(BaseModel): id: str; type: str; label: Optional[str]; agent_ref; instruction; max_retries ...   # :155 (extra="forbid")
class EdgeDefinition(BaseModel): id; from_ (alias "from"); to: Union[str, List[str]]; condition: Literal["always","on_success","on_error","on_timeout","on_condition"] = "on_success"; predicate: Optional[str]   # :246
class FlowDefinition(BaseModel): flow; version; description; created_at; updated_at; metadata; nodes: List[NodeDefinition]; edges: List[EdgeDefinition]   # :377 (nodes :421, edges :425)

# packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/
#   A2UINode.svelte — `{#if component === 'KPICard'} … {:else if component === 'Chart'} … 'DataTable' … 'Timeline' … 'InfoCard' … 'HtmlDocument' … 'Text' … 'Tabs'` chain, lines 62-133; dispatches on BARE name, never reads catalogId
#   a2ui-types.ts — WireComponent { id, component, child?, children?, metadata?, [prop]: unknown }, CreateSurface, A2UIEnvelope
#   a2ui-binding.ts — JSON-pointer resolver used by A2UINode
#   a2ui-chart-adapter.ts — Parrot Chart → ChartBlockData (legacy lane; untouched)
# packages/ai-parrot-server/ui/src/lib/components/visualizations/ECharts.svelte — `import * as echarts from "echarts/core"` (:10), lazy full-build import (:85)
# packages/ai-parrot-server/ui/src/lib/features.ts — `a2ui: __AGENTCHAT_A2UI__` (:31)

# Source artifacts (design reference, verified 2026-09-05; tracked copies under sdd/proposals/assets/a2ui-viz-core/, user working copies under artifacts/a2ui/ which IS gitignored at .gitignore:283)
#   viz-core.catalog.json — $id/catalogId "https://ai-parrot.dev/a2ui/catalogs/viz-core/1.0/catalog.json";
#     components Chart/Series/Stat; `instructions` = nine guideline rules; every $ref → a2ui.org common_types $defs that exist in the vendored copy
#   viz-core.example.jsonl — line 1 createSurface (surface catalogId = BASIC; per-component catalogId = viz-core), line 2 updateDataModel

# tests
# packages/ai-parrot/tests/outputs/a2ui/test_components_chart_datatable_map.py — golden pattern: GOLDEN_DIR = Path(__file__).parent / "golden"; _dump(tree); _validates(tree) wraps flat components under a Column root and calls validate_envelope
# packages/ai-parrot/tests/outputs/a2ui/golden/{chart,datatable,filterbar,htmldocument,infocard,infographic,kpicard,map,report,timeline}_lowered.json
# packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py — imports build_* from builders (lines 5-11); `_assert_conformant(envelope, *, origin)` at :49
# packages/ai-parrot/tests/outputs/a2ui/test_catalog_parity.py — test_derived_chart_schema_has_all_config_fields :22 (pattern for the Graph parity test)
# packages/ai-parrot/tests/outputs/a2ui/catalog/test_export.py — export_catalog_definition tests (pattern for the viz-core export test)
# packages/ai-parrot/tests/outputs/a2ui/catalog/test_validation_v1.py — resolve_catalog / _component_exists tests (pattern for the keyed-registry tests)
# packages/ai-parrot/tests/outputs/a2ui/test_catalog.py — registry tests (pattern for duplicate-pair / ambiguous-name tests)
# packages/ai-parrot/tests/outputs/a2ui/adapters/test_import_rule.py — _FORBIDDEN_IMPORTS = ("parrot.tools.dataset_manager", "parrot.bots", "parrot.clients") for adapters/, catalog/basic/, compat.py; AST-based for runtime/
# packages/ai-parrot/tests/outputs/a2ui/catalog/test_spec_vendored.py — vendored spec drift guard (catalog/basic/spec/*.json)
# packages/ai-parrot/tests/integration/test_frontend_guide_examples.py — every envelope example in the frontend guide validates
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `VIZ_CORE_CATALOG_ID` | `register_component(catalog_id=…)` | keyword already exists | `catalog/__init__.py:112` |
| keyed `_CATALOG` | `_component_exists` third branch | `entry.definition.catalog_id == resolved_catalog_id` becomes a keyed `get` | `catalog/__init__.py:293` |
| keyed `_CATALOG` | LLM-origin action gate | `_CATALOG.get(comp.component)` → `_CATALOG.get((resolved_catalog_id, comp.component))` | `catalog/__init__.py:498` |
| `catalog_instructions(catalog_ids)` | producer system prompt | `catalog_instructions()` call | `producer.py:211` |
| `export_catalog_definition(catalog_id=VIZ_CORE_CATALOG_ID)` | catalog filter + scoped instructions | existing filter `definition.catalog_id != catalog_id` | `catalog/export.py:261, :293` |
| `GraphComponent.SCHEMA` | `derive_schema()` | import-time call | `catalog/parrot/_derive.py:88` |
| `GraphComponent` | catalog registry | `@register_component("Graph", catalog_id=VIZ_CORE_CATALOG_ID)` | `catalog/__init__.py:107` |
| `catalog/viz_core/graph.py` | registration side effect | import in `catalog/viz_core/__init__.py`, which `catalog/__init__.py` imports after `catalog.parrot` | `catalog/parrot/__init__.py:13-24` (pattern) |
| `GraphComponent.lower()` | `to_mermaid()` | graph-source Text | new `graph/mermaid.py` |
| `build_graph()` | `build_surface()` | call with `origin=` and `data_model=`; then set `components[0].catalog_id` | `builders.py:50`, `models.py:431` |
| `build_graph()` | `compute_positions()` | fills `layout.positions` | new `graph/layout.py` |
| `flow_definition_to_graph()` | `FlowDefinition.model_dump(by_alias=True)` shape | Mapping input, no import | `definition.py:377` (caller side) |
| `intercepts()` | `resolve_catalog` | wraps it with the surface default | `catalog/__init__.py:233` |
| `EChartsRenderer._build_graph_option` | `_build_option` dispatch | `props["component"] == "Graph"` branch before chart handling | `echarts.py:128` |
| `InteractiveHTMLRenderer._render_graph` | `_INTERCEPTED` / `_lower_composites` | keyed membership via `intercepts()` + branch | `interactive_html.py:120`, `:666` |
| `SSRHTMLRenderer._lower_composites` | `Graph` intercept → `_graph_svg.render_graph_svg` | new branch beside the `Chart` check | `ssr_html.py:276` |
| `_graph_svg.render_graph_svg` | `DesignSystem` tokens | CSS variable names in SVG `fill`/`stroke` via `STATE_TO_STATUS` | `design_system/base.css`, `components.css` |
| `A2UIGraph.svelte` | `A2UINode.svelte` | catalog-aware `{:else if}` branch | `A2UINode.svelte:62-133` |
| `A2UIGraph.svelte` | `ECharts.svelte` | option prop | `visualizations/ECharts.svelte:10` |
| `test_build_graph` | `_assert_conformant` | conformance helper | `conformance/test_all_emitters.py:49` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.outputs.a2ui.catalog.viz_core` / `VIZ_CORE_CATALOG_ID` / `VIZ_CORE_INSTRUCTIONS` / `catalog_header_instructions`~~ — do not exist yet (Module 0 creates them)
- ~~`_CATALOG` keyed by `(catalog_id, name)`; `get_component(name, catalog_id=…)`; `list_components(catalog_id=…)`; `catalog_instructions(catalog_ids=…)`; `write_catalog_definition(catalog_id=…)`~~ — all bare-name / unscoped today
- ~~`Graph` component / `GRAPH_SCHEMA` in ANY catalog~~ — do not exist yet (this spec creates them under viz-core, NOT under `catalog/parrot/`)
- ~~`parrot.outputs.a2ui.graph` package (`models.py`, `mermaid.py`, `layout.py`)~~ — does not exist; **no mermaid parser anywhere in the repo**
- ~~`parrot.outputs.a2ui.adapters.flow` / `flow_definition_to_graph`~~ — does not exist
- ~~`builders.build_graph` / `build_timeline` / `build_update_data_model`~~ — not in `builders.__all__` (`builders.py:31-40`)
- ~~`selectAction` / `nodeAction` props~~ — `selectAction` exists only in the authored draft; neither is adopted; the standard `action` is used
- ~~`accessibleDescription` / `size` on any existing Parrot component~~ — viz-core only
- ~~`STATE_TO_STATUS` or any state→colour mapping in core~~ — new renderer-contract constant (satellite + UI); core carries no colours
- ~~`a2ui_renderers/_graph_svg.py`, `_graph_layout.py`, `_intercept.py`~~ — do not exist; layout lives in core `graph/layout.py` per this spec
- ~~`(catalog_id, name)` interception in any renderer; `catalogId` read in `A2UINode.svelte`~~ — all bare-name today
- ~~`packages/ai-parrot/src/parrot/outputs/a2ui/catalog/spec/`~~ — the vendored spec dir is `catalog/basic/spec/`
- ~~`packages/ai-parrot/src/parrot/outputs/a2ui/components/`~~ — the directory is `catalog/parrot/`
- ~~`ui/.../canvas/a2ui/A2UIGraph.svelte`, `A2UITimeline.svelte`~~ — do not exist; `Timeline` in `A2UINode.svelte` reuses the legacy infographic block
- ~~`ui/.../agents/infographic/blocks/InfographicChartBlock.svelte`~~ — wrong path; the block imported by `A2UINode.svelte` resolves to `agents/canvas/infographic/blocks/InfographicChartBlock.svelte`
- ~~`mermaid`, `dagre`, `elkjs`, `@xyflow/*`, `svelteflow`, `vega*`, `layerchart` in `ui/package.json`~~ — not present; do not add (ECharts `graph` series only)
- ~~`grandalf`, `graphviz`, `pydot`, `lark`, `pyparsing` in Python dependencies~~ — not present; do not add
- ~~`RendererCapabilities.supports_updates=True` on any satellite renderer~~ — all six declare `False`; unchanged here
- ~~`action` in `common_types.json#/$defs/ComponentCommon`~~ — not there (`id`, `catalogId`, `accessibility`, `metadata` only); `GRAPH_SCHEMA` must declare `action` itself
- ~~viz-core `Chart`, `Series`, `Stat`, `Treemap`, `coordinates`, `Stat.gauge`, `prepare/`, `parrot_vendor` gate, drift test~~ — belong to `a2ui-viz-core-charts`, not this spec
- ~~`FlowSurfaceBridge`, `build_workflow_surface`, `describe_flow_node`, SSE `updateDataModel` source~~ — belong to `a2ui-live-workflow-surface`
- ~~`FlowDefinition.to_a2ui_graph()`~~ — not added; callers pass `definition.model_dump(by_alias=True)`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Copy the `Chart` composite pattern (`catalog/parrot/chart.py`) for the module layout,
  the binding pass-through under a `parrot_*` extension key, and the golden test style in
  `test_components_chart_datatable_map.py` — but register under `VIZ_CORE_CATALOG_ID` and
  place the module under `catalog/viz_core/`.
- Keep `GraphSpec` the **only** vocabulary definition; the codec, the layout, the builder
  and the adapter all consume/produce `GraphSpec`. Never hand-edit `GRAPH_SCHEMA` beyond
  the single post-derivation merge that adds the `action` `$ref`.
- **What, never how.** No field in any `graph/` model may carry a colour, a font, a pixel
  size or a library option; `rankSep`/`nodeSep` are abstract layout units. Colour lives
  in the renderer contract (`STATE_TO_STATUS` → theme token). AC-13's schema test enforces
  this mechanically.
- Renderers intercept `(VIZ_CORE_CATALOG_ID, "Graph")` **before** lowering (same as
  `Chart`); the lowered form is only for lanes without a graph engine. Resolve `data` from
  the baked props (the bake pass has already replaced the binding) and overlay
  `state`/`label`/`meta` per node id.
- Rekey the registry **first** (Module 0) in its own commit, run the whole a2ui suite, and
  only then register `Graph`. Keep `get_component(name)` bare-name calls working by the
  unique-match rule; do not touch the seven call sites in this feature.
- All `graph/` modules are pure and synchronous (no I/O, no logging beyond
  `logging.getLogger(__name__)` at debug); keep them plain for testability and G8.
- Google-style docstrings, strict type hints, `ruff` clean; camelCase on the wire via
  Pydantic aliases, snake_case in Python.
- `MermaidCodecError` and `GraphTooLargeError` subclass `CatalogValidationError` so the LLM
  producer's validate-retry-degrade loop needs no new plumbing.
- Deterministic everything: stable sorts keyed on input order; golden files regenerated
  with the existing helper; `compute_positions` must be identical across runs and platforms
  (use integer rank/slot indices scaled at the end).

### Known Risks / Gotchas
- **Registry rekey blast radius**: `_CATALOG` is read at `catalog/__init__.py:498`
  (gate), `:293` (`_component_exists`), and by `get_component`/`list_components`;
  `catalog.basic` registers its 18 primitives through `register_component` at import
  time (`is_primitive=True`, `catalog_id=BASIC_CATALOG_ID`) — after the rekey they live
  under `(BASIC_CATALOG_ID, name)` and `_component_exists` for `DEFAULT_CATALOG_ID` must
  still answer True for them (Parrot `$ref`-includes Basic; keep the JSON-names check).
- **Ambiguity is future-dated**: no bare name is duplicated by this spec (viz-core has
  only `Graph`). The charts spec introduces viz-core `Chart` and must then update the
  `get_component("Chart")` call sites in `adapters/structured.py`, `interactive_html.py`
  and `ssr_html.py` to pass `DEFAULT_CATALOG_ID`. `test_bare_name_lookup_stays_unique_today`
  exists precisely to fail loudly at that moment.
- **Import order for registration**: `catalog/__init__.py` imports `catalog.parrot` for
  side effects; add `catalog.viz_core` **after** it and keep the same local-import
  discipline documented at `_component_exists` (circular import with `catalog.basic`).
- **Surface default vs component catalog**: builders keep the surface `catalogId` as
  Parrot's (docs promise this); the `Graph` component carries `catalogId: viz-core`
  explicitly. A `Graph` without its own `catalogId` in a Parrot-default surface is an
  `UNKNOWN_COMPONENT` — the LLM instructions must say so, and the producer's repair prompt
  will carry that code.
- **`action` not in `ComponentCommon`**: the vendored `agent_to_renderer.json` Component
  schema tolerates catalog props, and Parrot's `Component` model has `action`; but the
  viz-core `catalog_definition.json` export must declare `action` on `Graph` or a strict
  external renderer will reject it. Hence the post-derivation merge in Module 2.
- **G8 import rule**: `adapters/flow.py` must not import `parrot.bots` even under
  `TYPE_CHECKING` — the adapters guard is line-text based (`_FORBIDDEN_IMPORTS`), so a
  guarded import still fails. Accept `Mapping[str, Any]`; type the return, not the input.
- **Cycles in `flowchart`/`state`** are legal (loops are real workflows); only `kind="dag"`
  rejects them. Layout breaks cycles by reversing back edges and reports them; SVG draws the
  arrowhead on the original direction.
- **Mermaid label escaping**: labels containing `[ ] ( ) { } | " #` must be emitted quoted
  (`["..."]`), and `"` inside is emitted as `#quot;`. Round-trip tests cover this.
- **`[*]` in state diagrams** becomes synthetic `__start__`/`__end__` nodes on import and
  is re-emitted as `[*]` on export; a user-authored node literally named `__start__`
  collides — the codec raises `MermaidCodecError` rather than guess.
- **Mermaid drops viz-core props**: `accessibleDescription` and `size` have no mermaid
  form; round-trip tests compare modulo those fields and the docs say so.
- **Static node cap**: `MAX_STATIC_NODES = 200` (open question §8). Above it the static
  lanes degrade rather than time out; ECharts and the bundled UI have no cap.
- **Positions and `direction`**: positions are emitted in final orientation (already
  transposed/mirrored), so renderers never re-apply `direction`; they read it only for
  arrow/label placement hints.
- **Infographic sections**: `Graph` inside `sections[].components[]` uses the authored
  descriptor form `{"component": "Graph", "catalogId": VIZ_CORE, "properties": {...}}`;
  the `Infographic` lowering already recurses through `get_component(name).lower` — it
  must pass the descriptor's `catalogId` through once the keyed lookup lands; interactive-
  HTML's `_render_infographic` recurses into intercepted components — use `intercepts()`
  there too.
- **Bundled UI action dispatch**: the canvas has no action runtime yet (`supports_actions`
  is the workflow spec's job). `A2UIGraph.svelte` exposes `onNodeClick` and does nothing
  by default; do not invent an action transport here.
- **Sibling spec overlap**: `a2ui-viz-core-charts` will also edit `catalog/__init__.py`,
  `export.py`, `producer.py`, `echarts.py`, `ssr_html.py`, `pdf.py`, `interactive_html.py`
  and `A2UINode.svelte`. Keep this spec's edits additive and localized (new methods,
  one-line set/branch additions, the shell in its own commit) to make the later merge
  trivial.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pydantic` | present | `GraphSpec` family |
| `jsonschema` | present (FEAT-470 G8) | wire validation of `GRAPH_SCHEMA`; viz-core `catalog_definition.json` validity test |
| `networkx` | `>=3.0`, present in core (`pyproject.toml:170`) | optional helper for topological generations / cycle detection in `layout.py` |
| `echarts` | `^5.0.0`, present in bundled UI | `graph` series |
| `weasyprint` | present | PDF lane rasterizes inline SVG (no JS) |
| none new | — | mermaid codec and layered layout are hand-written |

---

## Worktree Strategy

- **Isolation**: `per-spec` — one worktree `feat-FEAT-529-a2ui-graph-component`, tasks
  sequential in dependency order. Module 0 (shell) is the first task and its own commit.
- **Parallelizable inside the worktree** (if a pool is used): after Modules 0–2 land,
  Module 3 (codec), Module 4 (layout) and Module 7 (UI) are disjoint files; Module 5 needs
  0+1+2+4; Module 6 needs 0+3+4; Module 8 last.
- **Cross-feature**: FEAT-527 is merged (no longer blocking). FEAT-528
  (`pg-recipe-store-and-agent-package-importability`) touches `recipes/`, not the catalog —
  independent. The not-yet-written `a2ui-viz-core-charts` depends on this spec's shell and
  shares the files listed in §7 gotchas; it may start from this worktree's shell commit
  before the whole feature merges. `a2ui-live-workflow-surface` must wait for this spec to
  merge.

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Wire form for graphs — *Resolved in brainstorm*: structured `nodes[]/edges[]` on the wire; pure Python mermaid codec both ways (import + export), never a mermaid string as the component.
- [x] Renderers native in v1 — *Resolved in brainstorm*: all four (navigator-frontend-next via contract doc, backend ECharts/interactive-HTML, bundled UI, SSR-HTML/PDF).
- [x] Authoring tiers — *Resolved in brainstorm*: LLM authors intent-level graphs (no positions, no `action`); deterministic code authors full detail (positions, `action`, `data` binding). Same component.
- [x] Extension mechanism — *Resolved in brainstorm (rev 2)*: Option D grammar catalog; one-component-per-kind and vendor-string-as-wire rejected; the tool-only `parrot_vendor` hint is scoped to `a2ui-viz-core-charts`.
- [x] Mermaid dialects in this round — *Resolved in brainstorm*: flowchart (+subgraph), stateDiagram-v2, sequenceDiagram; hand-written tokenizer, no parser dependency.
- [x] Layout engine — *Resolved in brainstorm*: hand-written pure-Python layered layout; force layout degrades to layered on static lanes. **Spec refinement**: it lives in core `graph/layout.py` (not the satellite) so `build_graph` can emit positions for every lane; `networkx` (already core) may assist.
- [x] Node click mechanism — *Resolved in brainstorm (rev 2)*: standard v1.0 component-level `action` with renderer-added `context.nodeId`/`nodeLabel`; the draft's `selectAction` and the rev-1 `nodeAction` are not adopted because the existing gate checks only `action`.
- [x] (rev 2) Where does `Graph` live? — *Resolved in brainstorm*: under the viz-core catalog; adopts `accessibleDescription`, `size`, standard `action`, semantic status mapping for node `state`; `layout.positions` stays on the wire (layout is preparation, not styling).
- [x] (rev 2) Who lands the viz-core catalog shell? — *Resolved in brainstorm*: this spec (Module 0); order becomes graph → charts → live surface.
- [x] (rev 2) Relationship to the Parrot `Chart`/`KPICard` — *Resolved in brainstorm*: separate catalog; legacy untouched; renderers dispatch on `(catalogId, name)`; no deprecation this round.
- [ ] (rev 2) Catalog id domain: keep the authored `https://ai-parrot.dev/a2ui/catalogs/viz-core/1.0/catalog.json` or align with `https://parrot.dev/catalogs/...`? Default: keep as authored; the constant is the single place to change. — *Owner: Jesus Lara*
- [ ] `MAX_STATIC_NODES` value — proposed 200; confirm or adjust after measuring SVG size/latency on a 200-node fixture. — *Owner: Jesus Lara*
- [ ] Should `flow_definition_to_graph` also accept a live `FlowDefinition` instance via duck typing (`getattr(definition, "model_dump", None)`) for caller convenience, still without importing `parrot.bots`? Default: yes, cheap and G8-safe. — *Owner: Jesus Lara*
- [ ] Sequence diagrams: render as left-to-right participant columns with ordered message edges (`direction: LR`, `meta.seq`) in v1, or defer native sequence rendering and only support codec round-trip + lowering? Default: codec + lowering only; renderers draw `kind: sequence` as an LR layered graph. — *Owner: Jesus Lara*
- [ ] Icon hint (`GraphNode.icon`): free string mapped by each renderer, or a closed enum shared with `KPICard.icon` (FEAT-527)? Default: free string, same as `KPICard.icon`. — *Owner: Jesus Lara*
- [ ] Should `get_component(name)` with an ambiguous name prefer the Parrot catalog instead of raising, to soften the charts-spec migration of the seven call sites? Default: raise (explicit beats silent). — *Owner: Jesus Lara*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-05 | Jesus Lara (with Claude) | Initial draft from `a2ui-rich-visualizations.brainstorm.md` (Option B, capability `a2ui-graph-component`); FEAT-529 reserved |
| 0.2 | 2026-09-05 | Jesus Lara (with Claude) | Re-run against brainstorm revision 2 (viz-core artifacts): `Graph` moves under the new `viz-core` catalog; adds Module 0 (catalog shell: `VIZ_CORE_CATALOG_ID`, `(catalog_id, name)`-keyed registry, scoped instructions, exporter, catalog-aware renderer/UI dispatch); adds `accessibleDescription`, `size`, state → status role contract, no-colour schema invariant; `selectAction` rejected in favour of the standard `action`; AC-0 added, AC-1/3/4/7–13 amended; FEAT-529 reused (no new reservation) |
