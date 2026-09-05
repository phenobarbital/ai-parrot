---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: A2UI `Graph` component — typed nodes/edges, mermaid codec, layered layout

**Feature ID**: FEAT-529
**Date**: 2026-09-05
**Author**: Jesus Lara (with Claude)
**Status**: draft
**Target version**: 0.30.0
**Source brainstorm**: `sdd/proposals/a2ui-rich-visualizations.brainstorm.md` (umbrella, Option B; this spec is its `a2ui-graph-component` capability)
**Sibling specs (same umbrella)**: `a2ui-typed-chart-specs` (not yet written), `a2ui-live-workflow-surface` (not yet written; depends on this spec)

---

## 1. Motivation & Business Requirements

### Problem Statement

There is no graph, DAG or flow component in the Parrot A2UI catalog. Agents that reason
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

The `a2ui-live-workflow-surface` spec (animated dev-loop timeline with drill-down) is
blocked on this component: it composes `Graph` with `Timeline` v2 and pushes node state
over the FEAT-469 SSE stream. This spec delivers the component; it does not deliver the
live bridge.

### Goals

- **G1 — `Graph` catalog composite.** A new Parrot composite `Graph` with a Pydantic-first
  schema (`kind`, `direction`, `nodes[]`, `edges[]`, `groups[]`, `layout`, `selection`,
  `data` binding), derived into `SCHEMA` by `derive_schema` (schema parity by
  construction, FEAT-473 G2), with a mandatory `lower()` to Basic primitives (FEAT-470 G4).
- **G2 — Bindable node state.** `Graph.data` is an optional data-model binding to an
  object keyed by node id whose values overlay `state`, `label` and `meta` at render time,
  so a graph authored once can be updated with `updateDataModel` alone.
- **G3 — Node click as a v1.0 action.** A `TOOL`-origin envelope may attach the standard
  component-level `action` to a `Graph`; renderers that support actions dispatch it on
  node click with `context.nodeId` (and `context.nodeLabel`) added. The existing D10b gate
  rejects it on `LLM` origin; no new gate is introduced.
- **G4 — Mermaid codec both ways.** Pure-Python `to_mermaid()` / `from_mermaid()` for the
  `flowchart` (incl. `subgraph`), `stateDiagram-v2` and `sequenceDiagram` dialects, with
  a canonical form that round-trips, and `MermaidCodecError` naming the offending line for
  anything outside the supported subset. No external parser dependency.
- **G5 — Deterministic layered layout in core.** A pure-Python layered layout
  (rank assignment, barycentre crossing reduction, coordinate assignment, group bounding
  boxes) producing `layout.positions`, used by the builder at build time and by every
  renderer when positions are absent. `networkx` (already a core hard dependency) may be
  used for topological generations and cycle detection; no new dependency.
- **G6 — Builder and flow adapter.** `build_graph(...)` in `builders.py`, and
  `flow_definition_to_graph(...)` in `adapters/flow.py` that maps a `FlowDefinition`-shaped
  mapping (nodes/edges/conditions/fan-out) to a `Graph` component **without importing
  `parrot.bots`** (G8 import rule preserved as-is).
- **G7 — Native rendering on all four lanes.** ECharts (`graph` series, `layout: "none"`
  with positions), interactive-HTML and SSR-HTML/PDF (inline SVG from positions, state
  colours from `DesignSystem` tokens), bundled Svelte canvas (`A2UIGraph.svelte` on the
  existing `ECharts.svelte` wrapper); navigator-frontend-next receives the contract in the
  frontend reference doc.
- **G8 — Useful degradation.** Lowering yields the edge list plus the mermaid source as a
  `Text` node (`parrot_role: graph-source`), so Adaptive Cards and any renderer without a
  graph engine show something copyable rather than a placeholder. Force layout on static
  lanes and graphs above the static node cap degrade with a recorded `degraded` entry.
- **G9 — Invariants kept.** A2UI core imports nothing from `parrot.bots`/`parrot.clients`
  (`adapters/test_import_rule.py` unchanged); `version` only in `serialization.py`;
  presentation semantics outside the schema only under `metadata.extensions.parrot_*`;
  `test_no_exec.py` holds; every new builder validates against the vendored v1.0 schema
  in the conformance suite.

### Non-Goals (explicitly out of scope)

- **Live updates, SSE bridge, `describe_flow_node`, `Timeline` v2, animation contract** —
  `a2ui-live-workflow-surface`.
- **`Chart.spec`, `DataContract`, preparer, `parrot_vendor` hint gate** —
  `a2ui-typed-chart-specs`. The `parrot_vendor: {mermaid}` hint named in the brainstorm is
  therefore NOT introduced here; this spec's mermaid compatibility is the codec only.
- **Mermaid dialects beyond flowchart / stateDiagram-v2 / sequenceDiagram** (class, ER,
  gantt, pie, gitGraph, mindmap), and mermaid `classDef`/`style`/`click`/`linkStyle`/
  `%%{init}` directives, notes, `loop`/`alt`/`par` blocks in sequences.
- **Force-directed layout on the server.** `layout.engine: "force"` is a hint for
  interactive renderers only; static lanes degrade to layered.
- **Editing graphs from the UI** (drag, add node), and persisting user-moved positions.
- **A mermaid string as the wire format** and **one component per graph kind** — rejected in
  the brainstorm (`sdd/proposals/a2ui-rich-visualizations.brainstorm.md`, Options A/C).
- **Changing navigator-frontend-next code** — contract doc only.

---

## 2. Architectural Design

### Overview

`Graph` follows the FEAT-470/473 composite pattern exactly: a Pydantic model family
(`GraphSpec` and children) is the single source of vocabulary; `derive_schema` turns it
into the wire `SCHEMA` with `data` replaced by the binding descriptor; `@register_component
("Graph")` publishes it into the Parrot catalog and, through the existing exporter, into
`catalog_definition.json`; `lower()` produces Basic primitives; renderers **intercept**
`Graph` before lowering (like `Chart`/`DataTable`/`Map`) and draw it natively.

Three pure modules under a new core package `parrot/outputs/a2ui/graph/` carry the logic
renderers share: `models.py` (the Pydantic spec), `mermaid.py` (codec) and `layout.py`
(layered layout → positions). Putting layout in core rather than the satellite (a
refinement of the brainstorm's file placement) is what lets the **builder** fill
`layout.positions` at build time, so the bundled UI and ECharts can draw with
`layout: "none"` and every lane shows the same picture. Renderers still call
`compute_positions()` themselves when an envelope arrives without positions (LLM-origin
envelopes never carry them).

Node interaction stays inside v1.0: a `Graph` may carry the standard component-level
`action` (event or function call). The renderer contract adds `nodeId`/`nodeLabel` to the
action's `context` when dispatching from a node click. Because `action` presence is
already rejected for `ProducerOrigin.LLM` by `validate_envelope`, nothing new is gated.
(The brainstorm sketched a dedicated `nodeAction` prop; the spec uses the standard `action`
instead — same behaviour, no new vocabulary.)

`flow_definition_to_graph` accepts the **mapping form** of a `FlowDefinition`
(`definition.model_dump(by_alias=True)`) so `adapters/` never imports `parrot.bots`; the
G8 import-rule test stays untouched. Node `type` maps to a shape (`start`/`end` → circle,
`decision`/`interactive_decision` → diamond, `synthesis` → hexagon, `tool` → subroutine,
`agent` and `dev_loop.*` → rounded), `EdgeDefinition.condition` becomes the edge label
(`on_condition` → the CEL `predicate` text, `on_error`/`on_timeout` → dashed), fan-out
`to: [..]` becomes one edge per target.

### Component Diagram

```
               ┌──────────────── core: parrot/outputs/a2ui ─────────────────┐
FlowDefinition ─(model_dump)─▶ adapters/flow.py::flow_definition_to_graph ──┐ │
mermaid text ────────────────▶ graph/mermaid.py::from_mermaid ─────────────┤ │
LLM producer ─(validate-retry-degrade)──────────────────────────────────────┤ │
                                                                            ▼ │
                    graph/models.py::GraphSpec ──▶ builders.build_graph ──▶ CreateSurface{Graph}
                          │                          │ (layout.positions filled
                          │                          │  via graph/layout.py)
                          ▼                          ▼
              catalog/parrot/graph.py           validate_envelope (catalog + D10b)
              SCHEMA = derive_schema(GraphSpec)      │
              lower() → Card{Column[title, edges…, mermaid source]}
                                                     ▼
   ┌───────────────── renderers (intercept "Graph" before lowering) ─────────────────┐
   │ echarts.py: graph series, layout:"none"+positions   → option JSON / HTML        │
   │ interactive_html.py / ssr_html.py / pdf.py: _graph_svg.py (positions → SVG,     │
   │     DesignSystem state tokens)                       → inline <svg>             │
   │ bundled UI canvas/a2ui/A2UIGraph.svelte on visualizations/ECharts.svelte        │
   │ adaptive_cards.py / folium_map.py: lowering only (edge list + mermaid source)   │
   └────────────────────────────────────────────────────────────────────────────────┘
graph/mermaid.py::to_mermaid ◀── GraphSpec (docs export, lowering's graph-source Text)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/outputs/a2ui/catalog/parrot/__init__.py` | modifies | import `graph` module for registration side effect |
| `parrot/outputs/a2ui/catalog/parrot/_derive.py::derive_schema` | uses | `derive_schema(GraphSpec, binding_fields=("data",), required=("nodes", "edges"))` |
| `parrot/outputs/a2ui/catalog/__init__.py::register_component` / `validate_envelope` | uses | no new gate; `Graph` registered `requires_actions=False`, `tool_only=False`, no `allowed_parents` (same as `Chart`) |
| `parrot/outputs/a2ui/builders.py` | extends | `build_graph`; `__all__` updated |
| `parrot/outputs/a2ui/adapters/__init__.py` | extends | export `flow_definition_to_graph` |
| `parrot/outputs/a2ui/catalog/export.py` | none (automatic) | `Graph` appears in `catalog_definition.json` via the registry; vendored-spec drift test unaffected |
| `parrot/outputs/a2ui/baking.py` | none (automatic) | `Graph.data` binding is resolved by the existing bake pass like `Chart.data` |
| `a2ui_renderers/echarts.py` (visualizations) | extends | `supported_components` adds `"Graph"`; `_build_graph_option()` |
| `a2ui_renderers/interactive_html.py` | extends | `_INTERCEPTED` adds `"Graph"`; `_render_graph()` |
| `a2ui_renderers/ssr_html.py`, `pdf.py` | extends | intercept `Graph` in `_lower_composites` → inline SVG; force-layout / node-cap degradation records |
| `a2ui_renderers/_graph_svg.py` (visualizations, new) | creates | positions + spec → SVG string using `DesignSystem` tokens |
| `formats/assets/design_system` (`DesignSystem`) | uses | `--accent-green/--accent-amber/--accent-red/--neutral-muted/--primary` tokens for node states |
| `ui/.../canvas/a2ui/A2UINode.svelte` | modifies | `{:else if component === 'Graph'}` → `A2UIGraph.svelte` |
| `ui/.../canvas/a2ui/A2UIGraph.svelte` (new) | creates | ECharts `graph` series via `visualizations/ECharts.svelte`; click → action dispatch hook (no-op in v1, see §8) |
| `ui/.../visualizations/ECharts.svelte` | uses | existing `echarts/core` wrapper |
| `docs/outputs/a2ui-v1.md`, `docs/frontend/agentdashboard-a2ui-reference.md` §5.2 | docs | new `Graph` section; composites count 10 → 11; `parrot_role` additions |
| `tests/outputs/a2ui/conformance/test_all_emitters.py` | extends | `test_build_graph` |
| `tests/outputs/a2ui/golden/` | extends | `graph_lowered.json` |

### Data Models

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

class GraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: Optional[str] = None            # defaults to id on render
    shape: Optional[NodeShape] = None      # renderer default: rect (state kind: rounded)
    group: Optional[str] = None            # GraphGroup.id
    state: Optional[NodeState] = None
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
    model_config = ConfigDict(extra="forbid")
    engine: LayoutEngine = "layered"
    rank_sep: Optional[float] = Field(default=None, alias="rankSep")
    node_sep: Optional[float] = Field(default=None, alias="nodeSep")
    positions: Optional[dict[str, Position]] = None   # REQUIRED when engine == "manual"

class GraphSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selectable: bool = False
    selected: Optional[str] = None

class GraphSpec(BaseModel):
    """Wire vocabulary of the ``Graph`` composite (camelCase aliases on the wire)."""
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    kind: GraphKind = "flowchart"
    direction: Direction = "TB"
    title: Optional[str] = None
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    groups: Optional[list[GraphGroup]] = None
    layout: Optional[GraphLayout] = None
    selection: Optional[GraphSelection] = None
    # INPUT-ONLY: replaced by the {"path": ...} binding descriptor in the derived schema.
    # Resolves to {node_id: {"state"?: NodeState, "label"?: str, "meta"?: dict}}.
    data: Optional[dict[str, dict[str, Any]]] = None

# Model-level validators (GraphSpec): unique node ids; every edge endpoint exists;
# every group member exists and belongs to at most one group; kind == "dag" ⇒ acyclic;
# layout.engine == "manual" ⇒ positions covers every node.
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
# Lowered tree (catalog/parrot/graph.py::GraphComponent.lower) — Basic primitives only
Card(id=<component.id>, metadata.extensions.parrot_variant="graph")
└─ Column
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
# parrot/outputs/a2ui/graph/__init__.py
from .models import GraphSpec, GraphNode, GraphEdge, GraphGroup, GraphLayout, GraphSelection, Position
from .mermaid import to_mermaid, from_mermaid, MermaidCodecError
from .layout import compute_positions, LayoutResult, MAX_STATIC_NODES

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

# parrot/outputs/a2ui/adapters/flow.py  (NEW — no parrot.bots import; G8 preserved)
def flow_definition_to_graph(
    definition: Mapping[str, Any],            # FlowDefinition.model_dump(by_alias=True) shape
    *,
    kind: GraphKind = "flowchart",
    direction: Direction = "TB",
    data_binding: str | None = None,
) -> GraphSpec: ...
    # nodes[].type → shape table (§2 Overview); edges[].condition/predicate → label/kind;
    # `to: list` → one GraphEdge per target; node `label` defaults to `id`.
```

```svelte
<!-- ui/src/lib/components/agents/canvas/a2ui/A2UIGraph.svelte (NEW) -->
<!-- props: properties (baked Graph props incl. layout.positions), dataModel, onNodeClick?(nodeId) -->
<!-- Renders ECharts `graph` series with layout:'none' from positions (fallback 'circular'
     when absent); node itemStyle.color from state; groups as ECharts markArea/graphic boxes;
     edge lineStyle.type from kind; arrows on; tooltip from meta. -->
```

---

## 3. Module Breakdown

### Module 1: Graph vocabulary — `graph/models.py`
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/graph/__init__.py`, `graph/models.py`
- **Responsibility**: `GraphSpec` family with camelCase aliases and the model-level
  validators listed in §2 Data Models; `GraphTooLargeError`; package exports.
- **Depends on**: `pydantic` only.

### Module 2: Catalog composite — `catalog/parrot/graph.py`
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/graph.py`, `catalog/parrot/__init__.py`
- **Responsibility**: `GRAPH_SCHEMA = derive_schema(GraphSpec, binding_fields=("data",),
  required=("nodes", "edges"))`; `GRAPH_INSTRUCTIONS` (LLM-facing: when to use, node/edge
  fields, shapes, states, "bind `data` for live state, never inline positions");
  `@register_component("Graph") class GraphComponent` with `lower()` per §2 Data Models;
  registration import. Golden `graph_lowered.json`.
- **Depends on**: Module 1, Module 3 (`to_mermaid` for the `graph-source` Text).

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
  through `build_surface(origin=...)`); `flow_definition_to_graph` per §2; `__all__`.
- **Depends on**: Modules 1, 2, 4.

### Module 6: Satellite renderers — SVG, ECharts, interactive-HTML, SSR/PDF
- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_graph_svg.py` (new), `echarts.py`, `interactive_html.py`, `ssr_html.py`, `pdf.py`
- **Responsibility**: `_graph_svg.render_graph_svg(props, *, theme) -> str` (uses
  `compute_positions` when `layout.positions` absent; shapes, arrowheads, labels, group
  boxes, state fill from `DesignSystem` tokens, `<title>` per node from `meta`);
  `EChartsRenderer._build_graph_option`, `supported_components |= {"Graph"}`;
  `interactive_html._INTERCEPTED |= {"Graph"}` + `_render_graph` embedding the SVG plus a
  collapsed `<details>` with the mermaid source; `ssr_html._lower_composites` intercepts
  `Graph` → SVG (PDF inherits); degradation records for `engine: force` (→ layered) and for
  `GraphTooLargeError` (→ lowered edge list, truncated to `MAX_STATIC_NODES` rows).
- **Depends on**: Modules 1, 3, 4.

### Module 7: Bundled UI — `A2UIGraph.svelte`
- **Path**: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIGraph.svelte` (new), `A2UINode.svelte`, `A2UIGraph.test.ts` (new)
- **Responsibility**: ECharts `graph` series on `visualizations/ECharts.svelte`; positions
  from props (fallback `circular`); state colours from the existing Tailwind tokens; groups
  as boxes; `selection.selected` highlighted; node click calls an optional `onNodeClick`
  prop (wired to action dispatch by `a2ui-live-workflow-surface`; no-op here). Dispatch
  branch in `A2UINode.svelte`. Vitest coverage for option building.
- **Depends on**: Module 2 (wire shape); `features.a2ui` flag already present.

### Module 8: Docs + conformance
- **Path**: `docs/outputs/a2ui-v1.md`, `docs/frontend/agentdashboard-a2ui-reference.md`,
  `tests/outputs/a2ui/conformance/test_all_emitters.py`, `tests/outputs/a2ui/test_catalog_parity.py`
- **Responsibility**: `Graph` section (schema, lowering, `parrot_role` additions `edge`,
  `edge-list`, `graph-source`; `parrot_variant: graph`; renderer matrix row; action click
  contract; mermaid codec subset); composites count 10 → 11 in the frontend reference;
  `test_build_graph` conformance; parity test that `GRAPH_SCHEMA` has every `GraphSpec`
  field.
- **Depends on**: Modules 2, 5, 6, 7.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_graphspec_rejects_dangling_edge` | 1 | edge to unknown node → `ValidationError` |
| `test_graphspec_rejects_duplicate_node_ids` | 1 | duplicate id → `ValidationError` |
| `test_graphspec_dag_rejects_cycle` | 1 | `kind="dag"` with A→B→A → `ValidationError`; `kind="flowchart"` accepts it |
| `test_graphspec_manual_requires_positions` | 1 | `engine="manual"` without full positions → `ValidationError` |
| `test_graph_schema_has_all_spec_fields` | 2 | every `GraphSpec` alias is a `GRAPH_SCHEMA` property; `data` is the binding descriptor (mirrors `test_derived_chart_schema_has_all_config_fields`) |
| `test_graph_registered_display_only` | 2 | `get_component("Graph").definition` → `requires_actions=False`, `tool_only=False`, `allowed_parents=None` |
| `test_graph_lower_golden` | 2 | lowered tree == `golden/graph_lowered.json`; validates via `validate_envelope` |
| `test_graph_lower_passes_data_binding_through` | 2 | `data={"path": "/nodes"}` → `parrot_graph_data` on the edge-list Column, unresolved |
| `test_graph_llm_origin_rejects_action` | 2 | `Graph` with `action` under `ProducerOrigin.LLM` → `ACTION_NOT_ALLOWED_FOR_LLM`; `TOOL` accepts |
| `test_graph_in_infographic_section_lowers` | 2 | `{"component": "Graph", "properties": {...}}` inside an `Infographic` section lowers recursively |
| `test_mermaid_roundtrip_flowchart` | 3 | `from_mermaid(to_mermaid(spec)) == spec` for flowchart with all 6 shapes, 3 edge kinds, labels both syntaxes, a subgraph |
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
| `test_build_graph_action_tool_origin_only` | 5 | `action=` with default TOOL origin OK; `origin=LLM` raises `CatalogValidationError` |
| `test_flow_definition_to_graph_shapes_and_edges` | 5 | start/end → circle, decision → diamond, tool → subroutine; `to: list` → N edges; `on_error` → dashed; `on_condition` label == predicate |
| `test_adapters_flow_has_no_bots_import` | 5 | covered by existing `adapters/test_import_rule.py` (no change) — asserted still green |
| `test_graph_svg_uses_state_tokens` | 6 | SVG contains one shape per node; `state="failed"` node fill references the red token |
| `test_graph_svg_arrowheads_and_edge_kinds` | 6 | `dashed` → `stroke-dasharray`; `thick` → larger `stroke-width`; marker-end present |
| `test_echarts_graph_option` | 6 | `series[0].type == "graph"`, `layout == "none"`, `data[i].x/y` from positions, `links` count == edges |
| `test_interactive_html_intercepts_graph` | 6 | output contains `<svg` and a `<details>` with the mermaid source; no degradation record |
| `test_ssr_force_layout_degrades_to_layered` | 6 | `engine="force"` → SVG rendered + `degraded[]` entry naming force |
| `test_ssr_graph_too_large_degrades` | 6 | > cap → lowered edge list + `degraded[]` entry |
| `test_pdf_graph_renders_svg` | 6 | PDF lane's pre-render HTML contains the graph SVG |
| `A2UIGraph.test.ts: builds echarts option from positions` | 7 | nodes carry x/y; links from edges; state → colour |
| `A2UIGraph.test.ts: falls back to circular without positions` | 7 | `layout === 'circular'` |
| `A2UINode.test.ts: dispatches Graph` | 7 | component `Graph` renders `A2UIGraph` |

### Integration Tests
| Test | Description |
|---|---|
| `test_build_graph` (conformance/test_all_emitters.py) | `build_graph(...)` envelope validates against vendored `agent_to_renderer.json`; lowered tree validates under `ProducerOrigin.LLM` |
| `test_flow_to_graph_to_mermaid_roundtrip` | dev-loop `FlowDefinition` fixture (mapping) → `flow_definition_to_graph` → `build_graph` → `to_mermaid` → `from_mermaid` equals the adapter's spec modulo positions |
| `test_graph_renders_on_every_registered_renderer` | for each `register_a2ui_renderer` name: render a `Graph` envelope; native lanes have no `Graph` degradation record, others have exactly one lowered `graph-source` Text |
| `test_catalog_definition_includes_graph` | `export_catalog_definition()["components"]["Graph"]` present with the derived schema |
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

GOLDEN_DIR / "graph_lowered.json"   # regenerated by the golden helper used in test_components_*.py
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC-1 `Graph` is registered in the Parrot catalog with `requires_actions=False`, `tool_only=False`, no `allowed_parents`; `GRAPH_SCHEMA` is derived from `GraphSpec` and contains every spec field with `data` as the binding descriptor (G1).
- [ ] AC-2 `GraphSpec` rejects dangling edges, duplicate ids, cycles when `kind="dag"`, and `manual` layout without full positions (G1).
- [ ] AC-3 `lower()` emits Basic primitives only: `Card{Column[title?, caption, edge-list, graph-source]}` with `parrot_variant: graph`; golden `graph_lowered.json` pinned; `data` binding passes through under `parrot_graph_data` (G1, G2, G8).
- [ ] AC-4 A `Graph` carrying `action` validates under `ProducerOrigin.TOOL` and is rejected under `ProducerOrigin.LLM` by the existing gate; no new gate code (G3).
- [ ] AC-5 `to_mermaid`/`from_mermaid` round-trip for flowchart (6 shapes, 3 edge kinds, both label syntaxes, subgraph), stateDiagram-v2 and sequenceDiagram fixtures; unsupported constructs raise `MermaidCodecError` with the right line number; `MermaidCodecError` is a `CatalogValidationError` (G4).
- [ ] AC-6 `compute_positions` is deterministic, positions every node, respects edge direction on non-reversed edges, handles cycles, honours all four `direction` values, boxes groups, and raises `GraphTooLargeError` above `MAX_STATIC_NODES` (G5).
- [ ] AC-7 `build_graph` fills `layout.positions` by default and validates through `build_surface`; `build_graph` is listed in `builders.__all__` and covered by the conformance suite against the vendored v1.0 schema (G6, G9).
- [ ] AC-8 `flow_definition_to_graph` maps the dev-loop fixture with the §2 shape/condition rules and `adapters/test_import_rule.py` stays green unchanged (G6, G9).
- [ ] AC-9 ECharts renderer emits a `graph` series with `layout: "none"` and positions; `supported_components` includes `Graph` (G7).
- [ ] AC-10 interactive-HTML, SSR-HTML and PDF embed an inline SVG for `Graph` with state colours from `DesignSystem` tokens; `engine: force` and oversize graphs degrade with a recorded `degraded` entry; Adaptive Cards and Folium show the lowered edge list + mermaid source (G7, G8).
- [ ] AC-11 Bundled UI renders `Graph` via `A2UIGraph.svelte` behind `features.a2ui`; vitest suites for option building and node dispatch pass (G7).
- [ ] AC-12 `docs/outputs/a2ui-v1.md` and the frontend reference document `Graph` (schema, lowering, click contract, mermaid subset, renderer row); the reference's `Graph` example validates in `test_frontend_guide_examples.py` (G7).
- [ ] AC-13 `test_no_exec.py`, `adapters/test_import_rule.py`, `catalog/test_spec_vendored.py` and every existing golden remain green; no existing envelope shape changes (G9).
- [ ] AC-14 `pytest packages/ai-parrot/tests/outputs/a2ui packages/ai-parrot-visualizations/tests -q` passes; `ruff check` clean on touched files; `npm test` in `packages/ai-parrot-server/ui` passes.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> All paths are relative to the repo root; core source is `packages/ai-parrot/src/parrot/`,
> visualizations satellite is `packages/ai-parrot-visualizations/src/parrot/`.
> Re-verified 2026-09-05 on `dev` after the FEAT-527 merge.

### Verified Imports
```python
from parrot.outputs.a2ui.catalog import register_component, get_component, validate_envelope   # catalog/__init__.py:107, (get_component in same module), :392
from parrot.outputs.a2ui.catalog.base import (                                                # catalog/base.py
    BasicNode, BasicTree, TabSpec, to_components,                                             # :101, :145, :164
    ComponentDefinition, ProducerOrigin,                                                      # :224, :89
    CatalogError, ComponentContractError, CatalogValidationError,                             # :295, :299, :307
    DEFAULT_CATALOG_ID, ACTION_NOT_ALLOWED_FOR_LLM, TOOL_ONLY_NOT_ALLOWED_FOR_LLM,             # :53, :78, :86
)
from parrot.outputs.a2ui.catalog.parrot._derive import derive_schema                          # catalog/parrot/_derive.py:88
from parrot.outputs.a2ui.models import (                                                      # models.py
    Component, CreateSurface, DataBinding, Action, Extensions, ComponentMetadata, UpdateDataModel,  # :400, (CreateSurface), :155, :250, :341, :364, :490
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
_STRUCTURED_INLINE_DATA_COMPONENTS = frozenset({"Chart", "DataTable", "Map"})   # line 104 — Graph is NOT added
def register_component(name: str, *, requires_actions: bool = False, catalog_id: str = DEFAULT_CATALOG_ID,
                       is_primitive: bool = False, allowed_parents: list[str] | None = None,
                       allowed_children: list[str] | None = None, tool_only: bool = False) -> Callable[[type], type]  # :107-116
def validate_envelope(envelope: CreateSurface | UpdateComponents, *, origin: ProducerOrigin = ProducerOrigin.TOOL,
                      surface_catalog_id: str | None = None) -> None   # :392-397; LLM-origin action gate :492, tool_only gate :515

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py
class BasicNode(BaseModel):                     # :101
    id: str | None = None; component: str; child: BasicNode | None; children: list[BasicNode] | ChildTemplate | None
    template_source: BasicNode | None; tabs: list[TabSpec] | None; metadata: ComponentMetadata | None   # :136-142
def to_components(tree: BasicNode, *, id_prefix: str = "blk") -> list[Component]   # :164
class ComponentDefinition(BaseModel):           # :224
    name; catalog_id; schema_ (alias "schema"); instructions; requires_actions; is_primitive; allowed_parents; allowed_children; tool_only  # :248-256

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/_derive.py
def derive_schema(model: type[BaseModel], *, binding_fields: Sequence[str], required: Sequence[str] = ()) -> dict[str, Any]   # :88-93
# strips Pydantic `title` annotations, keeps $defs, camelCases any snake_case top-level property

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/chart.py  (pattern to copy)
CHART_SCHEMA = derive_schema(StructuredChartConfig, binding_fields=("data",), required=("type", "x", "y"))
@register_component("Chart") class ChartComponent: SCHEMA; INSTRUCTIONS; def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree
# binding pass-through convention: extensions["parrot_series_data"] = props["data"]

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/timeline.py  (hand-written SCHEMA pattern)
TIMELINE_SCHEMA: dict[str, Any] = {...}   # :16

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/__init__.py — registration imports (chart, datatable, filterbar,
#   htmldocument, infocard, infographic, kpicard, map, report, timeline); `form` deliberately excluded

# packages/ai-parrot/src/parrot/outputs/a2ui/builders.py
__all__ = ["build_card", "build_chart", "build_datatable", "build_html_document", "build_infographic", "build_kpicard", "build_map", "build_surface"]  # :31-40
_ROOT_COMPONENT_ID = "root"   # :44
def build_surface(component: str, properties: dict[str, Any], *, surface_id: str, component_id: str = _ROOT_COMPONENT_ID,
                  data_model: dict[str, Any] | None = None, origin: ProducerOrigin = ProducerOrigin.LLM,
                  metadata: ComponentMetadata | None = None) -> CreateSurface   # :50-59

# packages/ai-parrot/src/parrot/outputs/a2ui/models.py
class Component(BaseModel):   # :400 — id, component, catalog_id (alias catalogId), child, children, weight, accessibility, checks, action: Action | None, metadata; extra="allow" (props top-level)
class DataBinding(BaseModel): path: str    # :155
class Action(BaseModel): event | function_call   # :250
class Extensions(RootModel[dict[str, Any]])      # :341 — official-prefix keys rejected; parrot_* allowed
class ComponentMetadata(BaseModel): extensions: Extensions | None   # :364, :373

# packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py
class RendererCapabilities(BaseModel): interactive: bool; supports_actions: bool; supports_updates: bool; output: str;
    supported_catalog_ids: list[str]; supported_components: set[str]   # :51, :70-75
def register_a2ui_renderer(name: str, capabilities: RendererCapabilities)   # :108

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py
_INTERCEPTED = {"Chart", "DataTable", "Infographic", "Map", "HtmlDocument"}   # :120
class InteractiveHTMLRenderer:  async def render(self, envelope: CreateSurface, *, bake: bool = True) -> RenderedArtifact  # :606
    def _lower_composites(self, envelope: CreateSurface) -> CreateSurface   # :666 — skips _INTERCEPTED
    def _render_chart(self, props: dict[str, Any], degradations: list[dict[str, Any]]) -> str   # :1024 (pattern for _render_graph)
    def _render_htmldocument(self, props: dict[str, Any]) -> str   # :1205

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py
_UNSUPPORTED_CHART_TYPES = frozenset({"gauge", "funnel", "waterfall", "heatmap", "treemap"})   # :84
class SSRHTMLRenderer: registered :118; _lower_composites(...) intercept pattern at :276 (`if comp.component == "Chart"`), degradations list appended via degradation_record
class PDFRenderer(SSRHTMLRenderer)   # pdf.py:99; def _chart_svg(props: dict) -> str at pdf.py:50 (bar-only; untouched by this spec)

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py
_SERIES_TYPE = {...}   # :41 ; _ROW_NATIVE_TYPES :59
@register_a2ui_renderer(_SURFACE_NAME, RendererCapabilities(interactive=False, supports_actions=False, supports_updates=False,
    output="application/json", supported_components={"Chart"}))   # :62-70
class EChartsRenderer(AbstractA2UIRenderer): async def render(...); def _build_option(self, props: dict[str, Any]) -> dict[str, Any]  # :128

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
#   A2UINode.svelte — `{#if component === 'KPICard'} … {:else if component === 'Chart'} … 'DataTable' … 'Timeline' … 'InfoCard' … 'HtmlDocument' … 'Text' … 'Tabs'` chain, lines 62-133
#   a2ui-types.ts — WireComponent { id, component, child?, children?, metadata?, [prop]: unknown }, CreateSurface, A2UIEnvelope
#   a2ui-binding.ts — JSON-pointer resolver used by A2UINode
# packages/ai-parrot-server/ui/src/lib/components/visualizations/ECharts.svelte — `import * as echarts from "echarts/core"` (:10), lazy full-build import (:85)
# packages/ai-parrot-server/ui/src/lib/features.ts — `a2ui: __AGENTCHAT_A2UI__` (:31)

# tests
# packages/ai-parrot/tests/outputs/a2ui/test_components_chart_datatable_map.py — golden pattern: GOLDEN_DIR = Path(__file__).parent / "golden"; _dump(tree); _validates(tree) wraps flat components under a Column root and calls validate_envelope
# packages/ai-parrot/tests/outputs/a2ui/golden/{chart,datatable,filterbar,htmldocument,infocard,infographic,kpicard,map,report,timeline}_lowered.json
# packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py — imports build_* from builders (lines 5-11); `_assert_conformant(envelope, *, origin)` at :49
# packages/ai-parrot/tests/outputs/a2ui/test_catalog_parity.py — test_derived_chart_schema_has_all_config_fields :22 (pattern for the Graph parity test)
# packages/ai-parrot/tests/outputs/a2ui/adapters/test_import_rule.py — _FORBIDDEN_IMPORTS = ("parrot.tools.dataset_manager", "parrot.bots", "parrot.clients") for adapters/, catalog/basic/, compat.py; AST-based for runtime/
# packages/ai-parrot/tests/outputs/a2ui/catalog/test_spec_vendored.py — vendored spec drift guard (catalog/basic/spec/*.json)
# packages/ai-parrot/tests/integration/test_frontend_guide_examples.py — every envelope example in the frontend guide validates
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `GraphComponent.SCHEMA` | `derive_schema()` | import-time call | `catalog/parrot/_derive.py:88` |
| `GraphComponent` | catalog registry | `@register_component("Graph")` | `catalog/__init__.py:107` |
| `catalog/parrot/graph.py` | registration side effect | import in `catalog/parrot/__init__.py` | `catalog/parrot/__init__.py:13-24` |
| `GraphComponent.lower()` | `to_mermaid()` | graph-source Text | new `graph/mermaid.py` |
| `build_graph()` | `build_surface()` | call with `origin=` and `data_model=` | `builders.py:50` |
| `build_graph()` | `compute_positions()` | fills `layout.positions` | new `graph/layout.py` |
| `flow_definition_to_graph()` | `FlowDefinition.model_dump(by_alias=True)` shape | Mapping input, no import | `definition.py:377` (caller side) |
| `EChartsRenderer._build_graph_option` | `_build_option` dispatch | `props["component"] == "Graph"` branch before chart handling | `echarts.py:128` |
| `InteractiveHTMLRenderer._render_graph` | `_INTERCEPTED` / `_lower_composites` | membership + intercept branch | `interactive_html.py:120`, `:666` |
| `SSRHTMLRenderer._lower_composites` | `Graph` intercept → `_graph_svg.render_graph_svg` | new branch beside the `Chart` check | `ssr_html.py:276` |
| `_graph_svg.render_graph_svg` | `DesignSystem` tokens | CSS variable names in SVG `fill`/`stroke` | `design_system/base.css`, `components.css` |
| `A2UIGraph.svelte` | `A2UINode.svelte` | new `{:else if component === 'Graph'}` branch | `A2UINode.svelte:62-133` |
| `A2UIGraph.svelte` | `ECharts.svelte` | option prop | `visualizations/ECharts.svelte:10` |
| `test_build_graph` | `_assert_conformant` | conformance helper | `conformance/test_all_emitters.py:49` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.outputs.a2ui.catalog.parrot.graph` / `Graph` component / `GRAPH_SCHEMA`~~ — do not exist yet (this spec creates them)
- ~~`parrot.outputs.a2ui.graph` package (`models.py`, `mermaid.py`, `layout.py`)~~ — does not exist; **no mermaid parser anywhere in the repo**
- ~~`parrot.outputs.a2ui.adapters.flow` / `flow_definition_to_graph`~~ — does not exist
- ~~`builders.build_graph` / `build_timeline` / `build_update_data_model`~~ — not in `builders.__all__` (`builders.py:31-40`)
- ~~a `nodeAction` prop~~ — the brainstorm's sketch; this spec uses the standard v1.0 component-level `action` instead
- ~~`a2ui_renderers/_graph_svg.py`, `_graph_layout.py`~~ — do not exist; layout lives in core `graph/layout.py` per this spec
- ~~`packages/ai-parrot/src/parrot/outputs/a2ui/catalog/spec/`~~ — the vendored spec dir is `catalog/basic/spec/`
- ~~`packages/ai-parrot/src/parrot/outputs/a2ui/components/`~~ — the directory is `catalog/parrot/`
- ~~`ui/.../canvas/a2ui/A2UIGraph.svelte`, `A2UITimeline.svelte`~~ — do not exist; `Timeline` in `A2UINode.svelte` reuses the legacy infographic block
- ~~`ui/.../agents/infographic/blocks/InfographicChartBlock.svelte`~~ — wrong path; the block imported by `A2UINode.svelte` resolves to `agents/canvas/infographic/blocks/InfographicChartBlock.svelte`
- ~~`mermaid`, `dagre`, `elkjs`, `@xyflow/*`, `svelteflow` in `ui/package.json`~~ — not present; do not add (ECharts `graph` series only)
- ~~`grandalf`, `graphviz`, `pydot`, `lark`, `pyparsing` in Python dependencies~~ — not present; do not add
- ~~`RendererCapabilities.supports_updates=True` on any satellite renderer~~ — all six declare `False`; unchanged here
- ~~`Chart.spec`, `DataContract`, `parrot/outputs/a2ui/prepare/`, `metadata.extensions.parrot_vendor` gate~~ — belong to `a2ui-typed-chart-specs`, not this spec
- ~~`FlowSurfaceBridge`, `build_workflow_surface`, `describe_flow_node`, SSE `updateDataModel` source~~ — belong to `a2ui-live-workflow-surface`
- ~~`FlowDefinition.to_a2ui_graph()`~~ — not added; callers pass `definition.model_dump(by_alias=True)`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Copy the `Chart` composite pattern (`catalog/parrot/chart.py`) for the module layout,
  the binding pass-through under a `parrot_*` extension key, and the golden test style in
  `test_components_chart_datatable_map.py`.
- Keep `GraphSpec` the **only** vocabulary definition; the codec, the layout, the builder
  and the adapter all consume/produce `GraphSpec`. Never hand-edit `GRAPH_SCHEMA`.
- Renderers intercept `Graph` **before** lowering (same as `Chart`); the lowered form is
  only for lanes without a graph engine. Resolve `data` from the baked props (the bake pass
  has already replaced the binding) and overlay `state`/`label`/`meta` per node id.
- All `graph/` modules are pure and synchronous (no I/O, no logging beyond `logging.getLogger(__name__)`
  at debug); async is not needed and would violate nothing, but keep them plain for
  testability and G8.
- Google-style docstrings, strict type hints, `ruff` clean; camelCase on the wire via
  Pydantic aliases, snake_case in Python.
- `MermaidCodecError` and `GraphTooLargeError` subclass `CatalogValidationError` so the LLM
  producer's validate-retry-degrade loop needs no new plumbing.
- Deterministic everything: stable sorts keyed on input order; golden files regenerated
  with the existing helper; `compute_positions` must be identical across runs and platforms
  (avoid float accumulation order differences — use integer rank/slot indices scaled at the
  end).

### Known Risks / Gotchas
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
- **Static node cap**: `MAX_STATIC_NODES = 200` (open question §8). Above it the static
  lanes degrade rather than time out; ECharts and the bundled UI have no cap.
- **Positions and `direction`**: positions are emitted in final orientation (already
  transposed/mirrored), so renderers never re-apply `direction`; they read it only for
  arrow/label placement hints.
- **Infographic sections**: `Graph` inside `sections[].components[]` uses the authored
  descriptor form `{"component": "Graph", "properties": {...}}`; the `Infographic` lowering
  already recurses through `get_component(name).lower`, and interactive-HTML's
  `_render_infographic` recurses into intercepted components — add `Graph` to that path's
  intercept check as well.
- **Bundled UI action dispatch**: the canvas has no action runtime yet (`supports_actions`
  is the workflow spec's job). `A2UIGraph.svelte` exposes `onNodeClick` and does nothing
  by default; do not invent an action transport here.
- **Sibling spec overlap**: `a2ui-typed-chart-specs` will also edit `echarts.py`,
  `ssr_html.py`, `pdf.py`, `interactive_html.py`. Keep this spec's edits additive and
  localized (new methods, one-line set/branch additions) to make the later merge trivial.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pydantic` | present | `GraphSpec` family |
| `jsonschema` | present (FEAT-470 G8) | wire validation of `GRAPH_SCHEMA` |
| `networkx` | `>=3.0`, present in core (`pyproject.toml:170`) | optional helper for topological generations / cycle detection in `layout.py` |
| `echarts` | `^5.0.0`, present in bundled UI | `graph` series |
| `weasyprint` | present | PDF lane rasterizes inline SVG (no JS) |
| none new | — | mermaid codec and layered layout are hand-written |

---

## Worktree Strategy

- **Isolation**: `per-spec` — one worktree `feat-FEAT-529-a2ui-graph-component`, tasks
  sequential in dependency order.
- **Parallelizable inside the worktree** (if a pool is used): after Modules 1–2 land,
  Module 3 (codec), Module 4 (layout) and Module 7 (UI) are disjoint files; Module 5 needs
  1+2+4; Module 6 needs 3+4; Module 8 last.
- **Cross-feature**: FEAT-527 is merged (no longer blocking). FEAT-528
  (`pg-recipe-store-and-agent-package-importability`) touches `recipes/`, not the catalog —
  independent. The not-yet-written `a2ui-typed-chart-specs` shares the four satellite
  renderer files (see §7 gotchas); whichever merges second rebases trivially if edits stay
  additive. `a2ui-live-workflow-surface` must wait for this spec to merge.

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Wire form for graphs — *Resolved in brainstorm*: structured `nodes[]/edges[]` on the wire; pure Python mermaid codec both ways (import + export), never a mermaid string as the component.
- [x] Renderers native in v1 — *Resolved in brainstorm*: all four (navigator-frontend-next via contract doc, backend ECharts/interactive-HTML, bundled UI, SSR-HTML/PDF).
- [x] Authoring tiers — *Resolved in brainstorm*: LLM authors intent-level graphs (no positions, no `action`); deterministic code authors full detail (positions, `action`, `data` binding). Same component.
- [x] Extension mechanism — *Resolved in brainstorm*: Option B (typed composite), one-component-per-kind and vendor-string-as-wire rejected; the tool-only `parrot_vendor` hint is scoped to `a2ui-typed-chart-specs`.
- [x] Mermaid dialects in this round — *Resolved in brainstorm* (Section 3 approved as written): flowchart (+subgraph), stateDiagram-v2, sequenceDiagram; hand-written tokenizer, no parser dependency.
- [x] Layout engine — *Resolved in brainstorm* (Section 3 approved): hand-written pure-Python layered layout; force layout degrades to layered on static lanes. **Spec refinement**: it lives in core `graph/layout.py` (not the satellite) so `build_graph` can emit positions for every lane; `networkx` (already core) may assist.
- [x] Node click mechanism — *Spec refinement of brainstorm*: standard v1.0 component-level `action` with renderer-added `context.nodeId`/`nodeLabel`, instead of a bespoke `nodeAction` prop. Behaviour identical; no new vocabulary or gate.
- [ ] `MAX_STATIC_NODES` value — proposed 200; confirm or adjust after measuring SVG size/latency on a 200-node fixture. — *Owner: Jesus Lara*
- [ ] Should `flow_definition_to_graph` also accept a live `FlowDefinition` instance via duck typing (`getattr(definition, "model_dump", None)`) for caller convenience, still without importing `parrot.bots`? Default: yes, cheap and G8-safe. — *Owner: Jesus Lara*
- [ ] Sequence diagrams: render as left-to-right participant columns with ordered message edges (`direction: LR`, `meta.seq`) in v1, or defer native sequence rendering and only support codec round-trip + lowering? Default: codec + lowering only; renderers draw `kind: sequence` as an LR layered graph. — *Owner: Jesus Lara*
- [ ] Icon hint (`GraphNode.icon`): free string mapped by each renderer, or a closed enum shared with `KPICard.icon` (FEAT-527)? Default: free string, same as `KPICard.icon`. — *Owner: Jesus Lara*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-05 | Jesus Lara (with Claude) | Initial draft from `a2ui-rich-visualizations.brainstorm.md` (Option B, capability `a2ui-graph-component`); FEAT-529 reserved |
