---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot, ai-parrot-server, docs]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [a2ui, viz-core, graph, c4, mermaid, architecture-diagrams]
---

# Feature Specification: C4 architecture diagrams as a `Graph` kind (`kind="c4"`) — vocabulary, Mermaid C4 codec, C4 layout, builder, lowering, bundled renderer

**Feature ID**: FEAT-754
**Date**: 2026-10-27
**Author**: Jesus Lara
**Status**: draft
**Target version**: TBD
**Origin**: NAV-10382 review (2026-10-27) — "the inline renderable catalog should grow; C4 architecture diagrams were named explicitly". No brainstorm/proposal exists for this feature; the design decisions below were taken in that review and refined against the FEAT-529 code.
**Parent component**: viz-core `Graph` (FEAT-529, `sdd/specs/a2ui-graph-component.spec.md`, merged). This spec EXTENDS that component; it introduces no new catalog component.
**Sibling features (same NAV-10382 review)**: FEAT-755 `inline-a2ui-component-routing` (LLM authoring lane: composite route `a2ui:Graph` + catalog-driven emitter — spec not yet written; design in `sdd/proposals/output-mode-intent-router.brainstorm.md` rev 2), FEAT-753 `MermaidDiagram` (opaque-source component — spec not yet written), FEAT-752 / FEAT-756 (not touched here).

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

The viz-core `Graph` component (FEAT-529) gives agents a TYPED, library-agnostic
way to render workflows, state machines, DAGs and call sequences:
`GraphSpec` (`packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py:179`)
is the single source of vocabulary, `to_mermaid`/`from_mermaid`
(`graph/mermaid.py:206,323`) is a dependency-free codec for three Mermaid
dialects, `compute_positions` (`graph/layout.py:228`) is a deterministic
server-side layout, `build_graph` (`builders.py:330`) emits a validated
envelope, `GraphComponent.lower()` (`catalog/viz_core/graph.py:76`) degrades to
Basic primitives, and `A2UIGraph.svelte` (bundled UI) draws it natively via
ECharts.

Software-architecture diagrams are the most frequently requested diagram family
that this vocabulary cannot express today. A C4 diagram (Simon Brown's
Context / Container / Component / Dynamic levels) is a graph, but one whose
nodes carry an **element type** (person, system, container, component — each
internal or external, plain, database or queue), a **technology** and a
**description**, whose relationships carry a technology and a placement hint,
and whose elements are nested inside **boundaries** (enterprise / system /
container). Modelling that today forces one of three bad options:

1. **Abuse `GraphNode.meta`** — opaque, uninterpreted by every renderer, invisible
   to the catalog schema, un-exportable to any standard notation.
2. **Author Mermaid text by hand** — exactly what FEAT-529 forbids on the wire
   (`GRAPH_INSTRUCTIONS`, `catalog/viz_core/graph.py:42`: "never author a
   mermaid string"); FEAT-753's opaque `MermaidDiagram` is the right home for
   arbitrary Mermaid, but it loses the typed node/edge model, the status-role
   overlay, the node-click `action` and the lowered fallback.
3. **A separate `C4Diagram` component** — a parallel vocabulary that duplicates
   nodes/edges/groups/layout/selection/`data`/`action`, a second lowering, a
   second renderer dispatch, and a second catalog entry the LLM must choose
   between.

The FEAT-529 vocabulary already has the right seams: `GraphKind` is a closed
`Literal` that the codec, layout and renderers dispatch on; `GraphGroup` is the
bounding-box primitive that boundaries need; node `state` → status role and the
component-level `action` are kind-agnostic. The missing piece is a **C4
vocabulary carried by the SAME `GraphSpec`** plus the codec, layout, lowering
and renderer rules that understand it.

### Goals

- **G1 — One component, one vocabulary.** `kind="c4"` is a fifth `GraphKind`.
  `GraphSpec` gains `level` and the C4 node/edge/group fields listed in §2
  Data Models; `GRAPH_SCHEMA` keeps being DERIVED from `GraphSpec`
  (`derive_schema`, `catalog/parrot/_derive.py:88`) so schema parity holds by
  construction (`test_graph_schema_has_all_spec_fields`,
  `tests/outputs/a2ui/test_catalog_parity.py:64`). No second catalog component.
- **G2 — Boundaries are groups.** C4 boundaries are modelled as `GraphGroup`
  entries with a new `parent` pointer (nesting) and a `c4Type` (boundary kind).
  The existing invariant "a node belongs to at most one group" is kept (the
  INNERMOST boundary); nested boxes are derived from the parent chain. See
  §2 Overview for why this beats boundary pseudo-nodes.
- **G3 — Mermaid C4 codec, both ways.** `to_mermaid()` emits canonical
  `C4Context` / `C4Container` / `C4Component` / `C4Dynamic` source using the
  official Mermaid C4 macros (`Person`, `System`, `Container`, `Component`,
  their `_Ext` / `Db` / `Queue` variants, `Boundary` / `Enterprise_Boundary` /
  `System_Boundary` / `Container_Boundary`, `Rel` / `BiRel` / `Rel_Back` /
  `Rel_U|D|L|R` / `Rel_Neighbor` / `Rel_Back_Neighbor`, `RelIndex` for
  Dynamic, `UpdateLayoutConfig`). `from_mermaid()` parses the same subset back.
  Round trip is **byte-stable** on canonical text and **object-equal modulo
  the documented lossy fields** (§3 Module 2). No new dependency.
- **G4 — Deterministic C4 layout, no new dependency.** `compute_positions`
  lays a `kind="c4"` spec out with C4 rules: persons on the first tier,
  internal elements in the middle grouped inside nested boundary boxes,
  external elements on the last tier ("at the edge"); boundaries wrap their
  members in rows (`shapeInRow`) and sit side by side (`boundaryInRow`). Same
  spec ⇒ same positions; `MAX_STATIC_NODES` cap unchanged. `networkx` (already
  a core dependency, `packages/ai-parrot/pyproject.toml:193`) is NOT needed for
  the C4 rules — they are not edge-driven.
- **G5 — Builder.** `build_graph(level=...)` passes the new field through and a
  thin `build_c4_diagram(...)` convenience builder exists for tool producers
  (TOOL origin by default, same as `build_graph`).
- **G6 — Lowered fallback.** `GraphComponent.lower()` degrades a C4 graph to
  boundaries → elements → relationships as Basic `Text`/`Column` primitives
  plus the C4 Mermaid source, consistent with the existing Graph lowering
  (`parrot_role` extensions, `parrot_variant: "graph"`). The non-C4 lowering is
  byte-identical to today (`tests/outputs/a2ui/golden/graph_lowered.json`).
- **G7 — Bundled reference renderer.** `A2UIGraph.svelte` draws `kind="c4"`
  with boundary frames, type-specific glyphs/captions, technology captions,
  dashed external elements and bidirectional arrows, keeping the status-role
  mapping and the `onNodeClick` hook; vitest coverage in `A2UIGraph.test.ts`.
- **G8 — LLM authoring hand-off.** The Graph catalog module gains C4 authoring
  notes and a default EN/ES utterance list ("C4 context diagram of…",
  "diagrama de contenedores…") that FEAT-755's catalog-driven emitter and
  phrase bank consume. This spec does not touch the router, the emitter or
  `DEFAULT_OUTPUT_MODE_ROUTES` (`parrot/bots/data.py:297`).
- **G9 — viz-core invariants preserved.** No colour, font, pixel or
  renderer-library vocabulary enters any model
  (`test_graph_schema_has_no_colour_vocabulary`, `test_catalog_parity.py:77`;
  `TestNoColourFontPixelVocabulary`, `graph/test_models.py:152`). `shapeInRow`
  / `boundaryInRow` are abstract counts, like `rankSep`/`nodeSep`.
- **G10 — Backwards compatible.** Every new field is optional with a `None`
  default; every existing `GraphSpec`, envelope, golden file, Mermaid fixture
  and renderer test keeps passing unchanged. The satellite renderers in
  `ai-parrot-visualizations` (`_graph_svg.py`, `echarts.py`,
  `interactive_html.py`) are NOT modified: a `kind="c4"` spec reaches them as
  a valid `GraphSpec` and draws as plain nodes with the C4 layout positions.

### Non-Goals (explicitly out of scope)

- PlantUML / C4-PlantUML / Structurizr DSL import or export. Only the Mermaid
  C4 dialect.
- Auto-discovery of architecture from code, repositories, deployments or the
  LLM wiki. A C4 `GraphSpec` is authored (by a tool, a builder caller, or —
  via FEAT-755 — the LLM).
- Server-side image rendering (PNG/SVG rasterization) of C4 diagrams. The
  static SVG lane (`ai-parrot-visualizations/.../_graph_svg.py`) is left as it
  is: it keeps drawing C4 nodes as generic nodes. C4 glyphs on the static and
  ECharts satellite lanes are a follow-up, not this feature.
- `C4Deployment` level (`Deployment_Node`, `Node`, `Node_L/R`) — the four
  levels the review named are context / container / component / dynamic.
- Mermaid C4 styling macros (`UpdateElementStyle`, `UpdateRelStyle`) and the
  `$sprite` / `$tags` / `$link` macro arguments — styling vocabulary, rejected
  by the parser like `classDef`/`style` are today (`mermaid.py:77-87`).
- Nested `subgraph` support in the flowchart / state codecs. `GraphGroup.parent`
  is accepted only for `kind="c4"` in this feature (validator), so the existing
  codecs never see a nested group (see §8 Q3).
- FEAT-753 `MermaidDiagram` internals. The only relationship: a C4 `GraphSpec`
  can be exported to a `MermaidDiagram.source` string via `to_mermaid()`.
- FEAT-755 internals (router labels, emitter, phrase-bank loader,
  `IntentRouterConfig`), FEAT-752 chips, FEAT-756 metric default shape.
- navigator-frontend-next, Adaptive Cards, Teams, Telegram or A2A rendering of
  C4 specifics — they receive the lowered tree (G6), nothing more.
- Interactive editing of C4 diagrams, collapsing boundaries, drill-down between
  levels (a Context node opening its Container diagram). `action` already
  carries `context.nodeId`; wiring a drill-down is a consumer's job.

---

## 2. Architectural Design

### Overview

**The whole feature is "teach the existing Graph pipeline a fifth kind".**
Every stage already dispatches on `GraphSpec.kind`; each stage gains one C4
branch, and the C4 vocabulary rides on the SAME models:

1. **Vocabulary (`graph/models.py`).** `GraphKind` grows `"c4"`. `GraphSpec`
   gains `level: C4Level`. `GraphNode` gains `c4Type`, `technology`,
   `description`. `GraphEdge` gains `technology`, `hint`, `bidirectional`.
   `GraphGroup` gains `parent`, `c4Type`. `GraphLayout` gains `shapeInRow`,
   `boundaryInRow`. `_validate_graph` (`models.py:229`) enforces the C4
   invariants (§2 Data Models) **fail-closed**: C4-only fields on a non-C4
   kind are a `ValueError`, so nothing is ever silently dropped by a codec or
   renderer that does not understand it.

2. **Boundaries as nested groups, not pseudo-nodes.** Two candidate shapes
   were weighed:
   - *Boundary nodes with `children`* — would put non-elements into
     `nodes[]`, so `compute_positions` would rank them from edges, every
     renderer (ECharts graph series, `_graph_svg`, `A2UIGraph`) would draw them
     as clickable nodes with a status role, `edges[]` endpoints would have to
     be forbidden from targeting them, and the dag/cycle validator would see
     them. Four new special cases in code that today has none.
   - *`groups[]` with a `parent` pointer* — reuses the one primitive that
     already means "bounding box around member nodes" (`GraphGroup`,
     `models.py:110`; `LayoutResult.group_boxes`, `layout.py:93`;
     `_render_group_box`, `_graph_svg.py:200`; `GraphGroupProps`,
     `A2UIGraph.svelte:40`). A node still belongs to at most one group (its
     innermost boundary); an outer boundary's box is the union of its direct
     members' positions and its child boundaries' boxes. Mermaid's
     `Boundary(...) { ... }` blocks nest the same way, so the codec maps 1:1.
   The second shape is chosen. `parent` chains are validated acyclic and
   group ids unique (a tightening — duplicate group ids were never meaningful).

3. **Codec (`graph/mermaid_c4.py`, new; `graph/mermaid.py` dispatch).** The
   C4 dialect is a macro language (`Macro(arg, "arg", ...)`) unlike the three
   existing line-oriented dialects, so it gets its own module with its own
   tokenizer, and `mermaid.py` only dispatches: `to_mermaid` on
   `spec.kind == "c4"` (`mermaid.py:218`), `from_mermaid` on a header that
   starts with `C4` (`mermaid.py:344-350`). The import is function-local in
   `mermaid.py` (the new module imports `MermaidCodecError` and the label
   helpers FROM `mermaid.py`; a top-level import both ways would be circular).

4. **Layout (`graph/layout_c4.py`, new; `graph/layout.py` dispatch +
   nested group boxes).** C4 placement is tier/grid driven, not edge driven
   (relationships in a C4 diagram do not imply rank). `compute_positions`
   (`layout.py:228`) dispatches to `compute_c4_positions` before cycle
   breaking; `_group_boxes` (`layout.py:337`) learns to box a group whose
   members are other groups (parent union + depth padding) — that part is
   kind-agnostic and makes `LayoutResult.group_boxes` complete for nested
   groups. `reversed_edges` is always empty for C4.

5. **Catalog (`catalog/viz_core/graph.py`).** `GRAPH_SCHEMA` picks the new
   fields up automatically (derived). `GRAPH_INSTRUCTIONS` mentions
   `kind="c4"` in one sentence. New module constants
   `GRAPH_C4_AUTHORING_NOTES` and `GRAPH_C4_UTTERANCES` are the hand-off to
   FEAT-755 (§8 Q1 for the attribute name the emitter will read). `lower()`
   grows a C4 branch (boundary list, element list, edge list with technology,
   C4 Mermaid source).

6. **Builder (`builders.py`).** `build_graph` gains `level=`; `build_c4_diagram`
   is a keyword-only wrapper that fixes `kind="c4"`, names `boundaries=` what
   `build_graph` calls `groups=`, and defaults `surface_id="c4-diagram"`.

7. **Bundled UI (`A2UIGraph.svelte` + test).** Types mirror the wire; the
   pure `buildGraphOption` gains a C4 path: per-`c4Type` ECharts symbol +
   caption, technology on a second label line, dashed border for `*_ext`,
   two arrowheads for `bidirectional`, and `option.graphic` boundary frames
   computed from positions when (and only when) positions are complete.

8. **Satellite renderers unchanged (G10).** `render_graph_svg`,
   `EChartsRenderer._build_graph_option`, `InteractiveHTMLRenderer._render_graph`
   rebuild a `GraphSpec` from the wire props; the new optional fields validate,
   `compute_positions` returns C4 positions, nodes draw as today. The
   conformance sweep (`TestGraphRendersOnEveryRegisteredRenderer`,
   `conformance/test_all_emitters.py:501`) gets a C4 twin to prove it.

### Component Diagram
```
                         GraphSpec(kind="c4", level, nodes[c4Type,technology,description],
                                   edges[technology,hint,bidirectional],
                                   groups[parent,c4Type], layout[shapeInRow,boundaryInRow])
                                              │  graph/models.py (M1)
          ┌───────────────────┬───────────────┼─────────────────┬──────────────────────┐
          ▼                   ▼               ▼                 ▼                      ▼
 graph/mermaid.py       graph/layout.py   catalog/viz_core/   builders.py        A2UIGraph.svelte (M6)
 to_mermaid/from_mermaid compute_positions graph.py (M4)      build_graph(level) ├─ buildGraphOption: c4 path
   │ kind=="c4" /        │ kind=="c4"      ├─ GRAPH_SCHEMA     build_c4_diagram   ├─ computeBoundaryFrames
   │ header "C4…"        ▼                 │  (derived, auto)  (M5)               └─ c4SymbolFor
   ▼                graph/layout_c4.py     ├─ GRAPH_INSTRUCTIONS (+c4)
 graph/mermaid_c4.py compute_c4_positions  ├─ GRAPH_C4_AUTHORING_NOTES ─┐
 to_mermaid_c4       (M3; tiers + grids;   ├─ GRAPH_C4_UTTERANCES ──────┼──▶ FEAT-755 emitter / phrase bank
 from_mermaid_c4     nested group_boxes)   └─ lower(): c4 branch ───────┘    (consumer, not touched here)
 (M2)                                             │
                                                  ▼
                               Basic primitives: Card{Column[description, title?, caption,
                               boundary-list, element-list, edge-list, graph-source]}  (G6)

 Unchanged consumers (G10): ai-parrot-visualizations _graph_svg / echarts / interactive_html,
 adapters/flow.py, A2UINode.svelte dispatch (isVizCoreGraph), FEAT-753 MermaidDiagram.source ◀─ to_mermaid()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `GraphSpec` / `GraphNode` / `GraphEdge` / `GraphGroup` / `GraphLayout` (`graph/models.py:179,57,87,110,141`) | extends | new optional fields + `GraphKind` member `"c4"`; `_validate_graph` (`:229`) gains the C4 and nesting invariants |
| `to_mermaid` / `from_mermaid` (`graph/mermaid.py:206,323`) | extends (dispatch) | one `kind == "c4"` branch, one `C4*` header branch; `MermaidCodecError` (`:126`) reused as the error type |
| `compute_positions` / `_group_boxes` / `LayoutResult` (`graph/layout.py:228,337,85`) | extends | C4 dispatch; nested group boxes; `MAX_STATIC_NODES` (`:60`) and `GraphTooLargeError` (`:68`) reused |
| `GraphComponent` / `GRAPH_SCHEMA` / `GRAPH_INSTRUCTIONS` (`catalog/viz_core/graph.py:64,35,42`) | extends | schema auto-derived; instructions sentence; `lower()` C4 branch; new authoring-notes/utterances constants |
| `build_graph` / `build_surface` (`builders.py:330,79`) | extends / uses | `level=` pass-through; `build_c4_diagram` delegates to `build_graph` |
| `ProducerOrigin`, `validate_envelope`, `ACTION_NOT_ALLOWED_FOR_LLM` (`catalog/__init__.py:743`, `catalog/base.py:99,78`) | uses (unchanged) | the D10b action gate applies to C4 graphs exactly as to any Graph |
| `A2UIGraph.svelte` (`buildGraphOption:131`, `GraphProperties:65`) | extends | C4 types + option path; `A2UINode.svelte:167,243-249` dispatch untouched (kind is inside props) |
| `derive_schema` (`catalog/parrot/_derive.py:88`) | uses (unchanged) | new aliases appear in `GRAPH_SCHEMA.properties` automatically (`by_alias=True`) |
| `flow_definition_to_graph` (`adapters/flow.py:63`) | none | never produces `kind="c4"`; untouched |
| `render_graph_svg`, `EChartsRenderer._build_graph_option`, `InteractiveHTMLRenderer._render_graph` (ai-parrot-visualizations `_graph_svg.py:75`, `echarts.py:396`, `interactive_html.py:1036`) | none (regression only) | must keep rendering a `kind="c4"` envelope without error; covered by the conformance twin |
| `DEFAULT_OUTPUT_MODE_ROUTES` (`parrot/bots/data.py:297`), `IntentRouterMixin` (`bots/mixins/intent_router.py`) | none | FEAT-755 consumes `GRAPH_C4_UTTERANCES`; this feature never edits the router or bank |

### Data Models
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py  (MODIFIED — additive)

GraphKind = Literal["flowchart", "state", "sequence", "dag", "c4"]            # was 4 members (models.py:47)

#: C4 abstraction level (Mermaid header: C4Context / C4Container / C4Component / C4Dynamic).
C4Level = Literal["context", "container", "component", "dynamic"]

#: C4 element type — exactly the 20 Mermaid C4 element macros, snake_case on the wire.
C4ElementType = Literal[
    "person", "person_ext",
    "system", "system_ext", "system_db", "system_db_ext", "system_queue", "system_queue_ext",
    "container", "container_ext", "container_db", "container_db_ext", "container_queue", "container_queue_ext",
    "component", "component_ext", "component_db", "component_db_ext", "component_queue", "component_queue_ext",
]

#: C4 boundary type — Enterprise_Boundary / System_Boundary / Container_Boundary / Boundary (generic).
C4BoundaryType = Literal["enterprise", "system", "container", "generic"]

#: Relationship placement hint — Mermaid Rel_U / Rel_D / Rel_L / Rel_R / Rel_Back / Rel_Neighbor / Rel_Back_Neighbor.
RelHint = Literal["up", "down", "left", "right", "back", "neighbor", "back_neighbor"]

class GraphNode(BaseModel):              # existing fields unchanged (models.py:78-84)
    c4_type: Optional[C4ElementType] = Field(default=None, alias="c4Type")   # c4-only; REQUIRED on every node when kind == "c4"
    technology: Optional[str] = None     # any kind (tooltip elsewhere); Mermaid: Container/Component 3rd arg
    description: Optional[str] = None    # any kind; Mermaid: Person/System 3rd arg, Container/Component 4th arg

class GraphEdge(BaseModel):              # existing fields unchanged (models.py:103-107)
    technology: Optional[str] = None     # any kind; Mermaid Rel 4th arg
    hint: Optional[RelHint] = None       # c4-only; forbidden when level == "dynamic" (RelIndex has no placement form)
    bidirectional: Optional[bool] = None # c4-only; True ⇒ BiRel; forbidden when level == "dynamic"

class GraphGroup(BaseModel):             # existing fields unchanged (models.py:122-124); `nodes` MAY be empty for a boundary that only holds sub-boundaries
    parent: Optional[str] = None         # c4-only (this feature); another GraphGroup.id; chain must be acyclic
    c4_type: Optional[C4BoundaryType] = Field(default=None, alias="c4Type")  # c4-only; None ⇒ generic `Boundary`

class GraphLayout(BaseModel):            # existing fields unchanged (models.py:159-162)
    shape_in_row: Optional[int] = Field(default=None, alias="shapeInRow", ge=1)        # abstract COUNT, not pixels
    boundary_in_row: Optional[int] = Field(default=None, alias="boundaryInRow", ge=1)  # set together or not at all (UpdateLayoutConfig takes both)

class GraphSpec(BaseModel):              # existing fields unchanged (models.py:216-226)
    level: Optional[C4Level] = None      # REQUIRED when kind == "c4"; forbidden otherwise

# Model-level validators appended to GraphSpec._validate_graph (all ValueError, pydantic → ValidationError):
#   V1  kind == "c4"  ⇒ level is not None; every node has c4_type.
#   V2  kind != "c4"  ⇒ level is None; no node c4_type; no edge hint/bidirectional; no group parent/c4_type;
#                       no layout shape_in_row/boundary_in_row.  (C4 vocabulary never leaks into a kind
#                       whose codec/renderers would silently drop it — fail closed.)
#   V3  group ids are unique; every group.parent references an existing group id (never itself); the
#       parent chain is acyclic (iterative walk, same style as _has_cycle, models.py:283).
#   V4  layout.shape_in_row and layout.boundary_in_row are both set or both None.
#   V5  level == "dynamic" ⇒ no edge carries hint or bidirectional (emitted as RelIndex, ordered by edges[]).
#   Existing invariants (unique node ids, edge endpoints exist, group members exist/at most one group,
#   dag acyclic, manual positions complete) are untouched.
# Forbidden-by-construction (G9): no new field name or enum value contains colour/color/palette/font,
# or the words `hex`/`px` (test_catalog_parity.py:77-87 regex); no Field(description=...) strings are added.

# Node state → status role, and the component-level `action`, are UNCHANGED for C4 nodes: a C4
# `GraphNode` may carry `state` (e.g. a container that is `failed`) and renderers paint the same role.

# Renderer contract additions for kind == "c4" (documented here, implemented in M6 for the bundled UI):
#   c4Type family → glyph/caption:  person* → person glyph, caption "Person";  *_db → database caption "[DB]";
#   *_queue → queue caption "[Queue]"; plain system/container/component → box; any *_ext → dashed border.
#   technology → second label line "[technology]"; description → tooltip; boundaries → frames labelled
#   "<label> [<c4Type> boundary]" nested by `parent`; bidirectional → arrowhead at both ends;
#   hint → ignored by renderers that compute their own layout (it is a Mermaid placement hint).

# Lowered tree (catalog/viz_core/graph.py::GraphComponent.lower, kind == "c4") — Basic primitives only
#   Card(parrot_variant="graph", parrot_c4_level=<level>) { Column [
#     Text(parrot_role="description")   accessibleDescription, or "C4 <level> diagram of N elements and M relationships"
#     Text(parrot_role="title")         only when title set
#     Text(parrot_role="caption")       "C4 <level> diagram"
#     Column(parrot_role="boundary-list") [ Text(parrot_role="boundary", parrot_c4_type=<c4Type|generic>, parrot_depth=<n>)
#                                           "<label or id> (<c4Type> boundary)" … ]       — omitted when no groups
#     Column(parrot_role="element-list")  [ Text(parrot_role="element", parrot_c4_type=<c4Type>, parrot_group=<group id>?)
#                                           "<label or id> [<c4Type>] · <technology>? — <description>?" … ]
#     Column(parrot_role="edge-list")     [ Text(parrot_role="edge", parrot_edge_kind?, parrot_condition?, parrot_technology?)
#                                           "<from> → <to> (<label>) via <technology>" … ]  (+ parrot_graph_data pass-through, as today)
#     Text(parrot_role="graph-source")  to_mermaid(spec)  (C4 dialect)
#   ] }
#   Non-C4 kinds: byte-identical to today's tree (golden graph_lowered.json unchanged).
```

### New Public Interfaces
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/graph/__init__.py  (re-exports added)
from .models import C4BoundaryType, C4ElementType, C4Level, RelHint
from .mermaid_c4 import from_mermaid_c4, to_mermaid_c4
from .layout_c4 import compute_c4_positions

# packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid_c4.py  (NEW)
def to_mermaid_c4(spec: GraphSpec) -> str: ...            # canonical C4 text; raises ValueError if spec.kind != "c4"
def from_mermaid_c4(text: str) -> GraphSpec: ...          # kind="c4"; raises MermaidCodecError (line-addressed)
# to_mermaid(spec) / from_mermaid(text) (graph/mermaid.py) dispatch to these — callers keep using the generic pair.

# packages/ai-parrot/src/parrot/outputs/a2ui/graph/layout_c4.py  (NEW)
def compute_c4_positions(spec: GraphSpec, *, rank_sep: float = 80.0, node_sep: float = 40.0) -> LayoutResult: ...
# compute_positions(spec) (graph/layout.py) dispatches here for kind == "c4" — same signature, same LayoutResult.

# packages/ai-parrot/src/parrot/outputs/a2ui/builders.py
def build_graph(*, ..., level: C4Level | None = None, ...) -> CreateSurface: ...      # one new keyword
def build_c4_diagram(
    *,
    level: C4Level,
    nodes: Sequence[GraphNode | dict[str, Any]],
    edges: Sequence[GraphEdge | dict[str, Any]],
    boundaries: Sequence[GraphGroup | dict[str, Any]] | None = None,
    direction: Direction = "TB",
    title: str | None = None,
    accessible_description: str | None = None,
    size: VizSize = "tile",
    layout: GraphLayout | dict[str, Any] | None = None,
    selection: GraphSelection | dict[str, Any] | None = None,
    data_binding: str | None = None,
    data_model: dict[str, Any] | None = None,
    action: Action | None = None,
    compute_layout: bool = True,
    surface_id: str = "c4-diagram",
    origin: ProducerOrigin = ProducerOrigin.TOOL,
) -> CreateSurface: ...

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/viz_core/graph.py
GRAPH_C4_AUTHORING_NOTES: Final[str]          # per-component authoring notes for the FEAT-755 emitter
GRAPH_C4_UTTERANCES: Final[tuple[str, ...]]   # default EN/ES phrase-bank utterances for the `a2ui:Graph` C4 intent

# packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIGraph.svelte  (<script module> exports)
export type C4Level = 'context' | 'container' | 'component' | 'dynamic';
export type C4ElementType = 'person' | 'person_ext' | ... ;      # the 20 values above
export type C4BoundaryType = 'enterprise' | 'system' | 'container' | 'generic';
export interface BoundaryFrame { id: string; label: string; depth: number; x: number; y: number; w: number; h: number }
export function c4SymbolFor(c4Type: C4ElementType | undefined): { symbol: string; caption: string; external: boolean };
export function computeBoundaryFrames(properties: GraphProperties): BoundaryFrame[];
# buildGraphOption(properties, resolveColor) keeps its signature; its result gains `graphic` frames for kind === 'c4'.
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

Mark which modules can be implemented by the targeted writer from an
already-decided TASK packet. Architecture decisions always stay with the
thinking model; eligibility only means "the design is complete enough that
writing the code is mechanical".

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: C4 vocabulary (`graph/models.py`) | yes | field list, aliases, Literals and validators V1–V5 fixed in §2 Data Models; iterative parent-chain walk; `extra="forbid"` kept | — |
| M2: Mermaid C4 codec (`graph/mermaid_c4.py` + dispatch) | yes | grammar, macro tables, canonical emission order, arity rules, lossy-field list and error reasons fixed below; reuses `MermaidCodecError`, `_escape_label`, `_unescape_label`, `_prepare_lines` | — |
| M3: C4 layout (`graph/layout_c4.py` + `layout.py` dispatch/nested boxes) | yes | tier rules, grid wrap, defaults (4 / 2), padding-by-depth, integer slot arithmetic, `reversed_edges == []` fixed below | — |
| M4: Catalog — lowering, instructions, authoring notes, utterances | yes | lowered tree fixed in §2 Data Models; golden `graph_c4_lowered.json` produced by the task and committed; utterance list fixed below | — |
| M5: Builder (`build_graph(level=)`, `build_c4_diagram`) | yes | signature fixed in §2 New Public Interfaces; pure delegation | — |
| M6: Bundled UI (`A2UIGraph.svelte` + vitest) | yes | type additions, symbol/caption table, frame algorithm (mirror of `_group_boxes`), dashed/bidirectional rules and test names fixed below | — |
| M7: Docs + conformance + fixtures | yes | doc sections, insertion anchors, conformance test names and fixture path fixed below | — |

### Module 1: C4 vocabulary — `graph/models.py`
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py` (MODIFY) + `graph/__init__.py` (re-exports)
- **Responsibility**: carry the C4 vocabulary on the existing models; enforce V1–V5 in `_validate_graph`; export the four new Literals.
- **Depends on**: nothing new (pydantic v2 already used).
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py  (modifies models.py:47, :78-84, :103-107, :122-124, :159-162, :216-226, :229-281)
  GraphKind = Literal["flowchart", "state", "sequence", "dag", "c4"]   # verified: models.py:47 (4 members today)
  C4Level = Literal["context", "container", "component", "dynamic"]
  C4ElementType = Literal["person", "person_ext", "system", "system_ext", "system_db", "system_db_ext",
                          "system_queue", "system_queue_ext", "container", "container_ext", "container_db",
                          "container_db_ext", "container_queue", "container_queue_ext", "component",
                          "component_ext", "component_db", "component_db_ext", "component_queue",
                          "component_queue_ext"]
  C4BoundaryType = Literal["enterprise", "system", "container", "generic"]
  RelHint = Literal["up", "down", "left", "right", "back", "neighbor", "back_neighbor"]

  class GraphNode(BaseModel):                                   # verified: models.py:57
      """… (existing docstring) … c4_type/technology/description: see spec §2 Data Models."""
      c4_type: Optional[C4ElementType] = Field(default=None, alias="c4Type")
      technology: Optional[str] = None
      description: Optional[str] = None

  class GraphEdge(BaseModel):                                   # verified: models.py:87 (populate_by_name=True at :101)
      technology: Optional[str] = None
      hint: Optional[RelHint] = None
      bidirectional: Optional[bool] = None

  class GraphGroup(BaseModel):                                  # verified: models.py:110 — model_config gains populate_by_name=True (alias c4Type)
      parent: Optional[str] = None
      c4_type: Optional[C4BoundaryType] = Field(default=None, alias="c4Type")

  class GraphLayout(BaseModel):                                 # verified: models.py:141 (populate_by_name=True at :157)
      shape_in_row: Optional[int] = Field(default=None, alias="shapeInRow", ge=1)
      boundary_in_row: Optional[int] = Field(default=None, alias="boundaryInRow", ge=1)

  class GraphSpec(BaseModel):                                   # verified: models.py:179
      level: Optional[C4Level] = None

      @model_validator(mode="after")
      def _validate_graph(self) -> GraphSpec:                   # verified: models.py:229 — existing checks kept, V1–V5 appended before `return self` (:281)
          """Existing invariants + V1 (c4 ⇒ level & c4_type), V2 (c4-only fields ⇒ kind c4),
          V3 (group ids unique, parent exists ≠ self, chain acyclic), V4 (shapeInRow/boundaryInRow together),
          V5 (dynamic ⇒ no hint/bidirectional). All via ValueError."""

      def _group_parent_cycle(self) -> Optional[str]:
          """Return the first group id whose `parent` chain loops back on itself, else None (iterative)."""
  ```
  `__all__` (models.py:30-45) and `graph/__init__.py` (:13-28, :30-52) gain
  `C4BoundaryType`, `C4ElementType`, `C4Level`, `RelHint`.

### Module 2: Mermaid C4 codec — `graph/mermaid_c4.py` (+ dispatch in `graph/mermaid.py`)
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid_c4.py` (CREATE); `graph/mermaid.py` (MODIFY: two dispatch branches + module docstring); `graph/__init__.py` (re-export)
- **Responsibility**: emit canonical Mermaid C4 text from a `kind="c4"` spec and parse the same subset back. Dependency-free (regex tokenizer, like `mermaid.py`).
- **Depends on**: Module 1; `MermaidCodecError`, `_escape_label`, `_unescape_label`, `_prepare_lines`, `_IDENT` from `mermaid.py:126,146,153,174,109`.
- **Decided grammar** (canonical emission; parser accepts the same plus free whitespace and `%%` comments):
  - Header by `level`: `C4Context` | `C4Container` | `C4Component` | `C4Dynamic`. `direction` has no C4 form (parsed specs get `"TB"`).
  - `title <text>` — second line, only when `spec.title` is set (raw text, trailing-stripped).
  - Elements: nodes with no group first (input order), then boundaries in `groups[]` order; inside a boundary: its direct member nodes (`group.nodes` order), then its child boundaries (`groups[]` order), 4-space indent per depth. Macro by `c4_type` (table: `person→Person`, `person_ext→Person_Ext`, `system→System`, `system_ext→System_Ext`, `system_db→SystemDb`, `system_db_ext→SystemDb_Ext`, `system_queue→SystemQueue`, `system_queue_ext→SystemQueue_Ext`, `container→Container`, `container_ext→Container_Ext`, `container_db→ContainerDb`, `container_db_ext→ContainerDb_Ext`, `container_queue→ContainerQueue`, `container_queue_ext→ContainerQueue_Ext`, `component→Component`, `component_ext→Component_Ext`, `component_db→ComponentDb`, `component_db_ext→ComponentDb_Ext`, `component_queue→ComponentQueue`, `component_queue_ext→ComponentQueue_Ext`). Person/System family args: `(id, "label", "description")`; Container/Component family: `(id, "label", "technology", "description")`. Trailing unset args are omitted; an unset `technology` before a set `description` is emitted as `""`. Label defaults to `id` (and is re-inferred as `None` on parse when equal to the id, same collapsing rule as `mermaid.py:38-40`). All string args double-quoted; `"` inside → `#quot;` (`_escape_label` convention).
  - Boundaries: `Enterprise_Boundary(id, "label") {`, `System_Boundary(id, "label") {`, `Container_Boundary(id, "label") {`, generic/None → `Boundary(id, "label") {`; closed by `}` on its own line.
  - Relationships after all elements, in `edges[]` order. `level != "dynamic"`: macro by (`bidirectional`, `hint`): `BiRel` if bidirectional, else `Rel` / `Rel_Back` / `Rel_U` / `Rel_D` / `Rel_L` / `Rel_R` / `Rel_Neighbor` / `Rel_Back_Neighbor`; args `(from, to, "label", "technology")` — label is positional-required in Mermaid, emitted as `""` when `None` (parsed back to `None`). `level == "dynamic"`: `RelIndex("<n>", from, to, "label", "technology")` with `n` = 1-based position in `edges[]`; the parser orders edges by the index (ties/gaps → `MermaidCodecError`).
  - `UpdateLayoutConfig($c4ShapeInRow="<shapeInRow>", $c4BoundaryInRow="<boundaryInRow>")` — last line, only when both are set (V4).
  - Parser also accepts Mermaid's spelled aliases `Rel_Up`/`Rel_Down`/`Rel_Left`/`Rel_Right` (canonical emit is the short form).
  - **Rejected** (`MermaidCodecError`, line-addressed, reason text fixed): `UpdateElementStyle` / `UpdateRelStyle` ("styling is not in the supported subset"); any `$sprite=` / `$tags=` / `$link=` argument ("sprite/tags/link arguments are not in the supported subset"); more positional args than the macro's arity; an unknown macro; an id not matching `_IDENT`; an unbalanced `}`; `Deployment_Node` / `Node` (C4Deployment — non-goal); `%%{init}` (already rejected by `_prepare_lines`, `mermaid.py:191`).
  - **Documented loss** (fields with no C4 Mermaid form, dropped on export, defaults on import): `accessible_description`, `size`, `direction`, `selection`, `data`, `layout.engine`/`rank_sep`/`node_sep`/`positions`, node `shape`/`state`/`icon`/`meta`/`group`-less ordering nuance below, edge `kind`/`condition`. **Round-trip contract**: (a) byte-stable — `to_mermaid(from_mermaid(text)) == text` for any text `to_mermaid` produced; (b) object-equal modulo the lossy fields — `from_mermaid(to_mermaid(spec)).model_dump(exclude=LOSSY) == spec.model_dump(exclude=LOSSY)` when `spec.nodes` is already in canonical declaration order (ungrouped first, then per boundary). A spec whose `nodes[]` interleaves grouped and ungrouped nodes round-trips to the canonical order (edges/groups unchanged) — this is inherent to C4 syntax (an element must be declared inside its boundary block) and is stated in the module docstring.
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid_c4.py  (new)
  from parrot.outputs.a2ui.graph.mermaid import MermaidCodecError, _escape_label, _unescape_label, _prepare_lines, _IDENT  # verified: mermaid.py:126,146,153,174,109
  from parrot.outputs.a2ui.graph.models import GraphEdge, GraphGroup, GraphNode, GraphSpec            # verified: models.py:87,110,57,179

  __all__ = ["from_mermaid_c4", "to_mermaid_c4", "C4_LOSSY_FIELDS"]

  #: GraphSpec fields (dotted for nested) with no Mermaid C4 representation — the "modulo" set of the round-trip contract.
  C4_LOSSY_FIELDS: frozenset[str]

  _LEVEL_HEADER: dict[str, str]          # level → "C4Context" | "C4Container" | "C4Component" | "C4Dynamic"
  _ELEMENT_MACRO: dict[str, str]         # C4ElementType → macro name (table above); _MACRO_ELEMENT is its inverse
  _BOUNDARY_MACRO: dict[Optional[str], str]
  _REL_MACRO: dict[tuple[bool, Optional[str]], str]   # (bidirectional, hint) → macro; inverse accepts the spelled aliases

  def to_mermaid_c4(spec: GraphSpec) -> str:
      """Emit canonical Mermaid C4 source for a ``kind="c4"`` spec (trailing newline included).

      Raises:
          ValueError: if ``spec.kind != "c4"`` (the generic ``to_mermaid`` never calls it otherwise).
      """

  def from_mermaid_c4(text: str) -> GraphSpec:
      """Parse Mermaid C4 source (C4Context/C4Container/C4Component/C4Dynamic) into a ``kind="c4"`` GraphSpec.

      Raises:
          MermaidCodecError: empty source, unknown header, unknown/unsupported macro, styling or
              sprite/tags/link arguments, arity violation, bad identifier, unbalanced boundary block,
              duplicate/gapped RelIndex — always naming the offending line.
      """

  def _split_macro_args(line_no: int, content: str, raw: str) -> list[str]:
      """Split a macro argument list on top-level commas, honouring double quotes; strips and unescapes each."""

  def _emit_element(node: GraphNode, depth: int) -> str: ...
  def _emit_boundary_open(group: GraphGroup, depth: int) -> str: ...
  def _emit_rel(edge: GraphEdge, index: int, dynamic: bool) -> str: ...
  ```
  ```python
  # packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py  (modifies mermaid.py:218 and :344-350; docstring :1-51 lists the C4 dialect)
  def to_mermaid(spec: GraphSpec) -> str:                      # verified: mermaid.py:206
      """… + ``kind="c4"`` delegates to :func:`mermaid_c4.to_mermaid_c4` (function-local import — mermaid_c4 imports this module)."""

  def from_mermaid(text: str) -> GraphSpec:                    # verified: mermaid.py:323
      """… + a header starting with ``C4`` delegates to :func:`mermaid_c4.from_mermaid_c4` (before the 'unrecognized header' raise, :350)."""
  ```

### Module 3: C4 layout — `graph/layout_c4.py` (+ dispatch and nested boxes in `graph/layout.py`)
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/graph/layout_c4.py` (CREATE); `graph/layout.py` (MODIFY: dispatch in `compute_positions`, nested-aware `_group_boxes`); `graph/__init__.py` (re-export)
- **Responsibility**: deterministic, dependency-free C4 placement; nested boundary boxes for every kind.
- **Depends on**: Module 1; `LayoutResult`, `Position`, `GraphTooLargeError`, `MAX_STATIC_NODES`, `_GROUP_PADDING`, `_LAYOUT_PADDING` from `layout.py:85,50,68,60,64,65`.
- **Decided rules** (integer slot arithmetic, scaled by `rank_sep`/`node_sep` at the end, exactly like `layout.py:228-290`):
  1. **Tiers** (rank axis): tier 0 = nodes whose `c4_type` ∈ {`person`, `person_ext`}; tier 2 = every other `*_ext` node (external systems/containers/components, "at the edge"); tier 1 = everything else (internal elements). `direction` `TB` (C4 default) stacks tiers top→bottom, `LR` left→right, `BT`/`RL` mirror the rank axis via the existing `_extent` (`layout.py:310`).
  2. **Tier 1 grid**: top-level boundaries (groups with `parent is None`) in `groups[]` order, laid in rows of `boundary_in_row` (default **2**) boxes; ungrouped tier-1 nodes form an implicit leading pseudo-box. Inside a boundary: direct member nodes wrap in rows of `shape_in_row` (default **4**) slots, then child boundaries (recursively, same rule) stacked below. Each boundary's footprint = max(row width, child widths) × (rows + children heights) + 2 × `_GROUP_PADDING` × depth; boxes never overlap because footprints are computed bottom-up before placement.
  3. **Tiers 0 and 2**: single-level rows wrapped at `shape_in_row`, left-aligned (no centring — keeps the arithmetic exact).
  4. Cross-axis slot = `node_sep`; rank-axis slot = `rank_sep`; boundary rows add `_GROUP_PADDING` between them. `width`/`height` as in `_extent`.
  5. `group_boxes`: every boundary (nested included) — produced by the shared, now nested-aware `_group_boxes` (`layout.py:337`): a group's box is the padded union of its direct members' positions AND its child groups' boxes (children first, depth-first; a group with neither is skipped as today, `layout.py:341`).
  6. `reversed_edges == []` always; `MAX_STATIC_NODES` cap raises `GraphTooLargeError` first, as today (`layout.py:251-253`).
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # packages/ai-parrot/src/parrot/outputs/a2ui/graph/layout_c4.py  (new)
  from parrot.outputs.a2ui.graph.layout import (                     # verified: layout.py:52,60,64,65,68,85
      MAX_STATIC_NODES, _GROUP_PADDING, _LAYOUT_PADDING, GraphTooLargeError, LayoutResult, _group_boxes, _extent,
  )
  from parrot.outputs.a2ui.graph.models import Direction, GraphGroup, GraphNode, GraphSpec, Position   # verified: models.py:48,110,57,179,127

  __all__ = ["DEFAULT_BOUNDARY_IN_ROW", "DEFAULT_SHAPE_IN_ROW", "compute_c4_positions"]

  DEFAULT_SHAPE_IN_ROW: int = 4        # Mermaid's $c4ShapeInRow default
  DEFAULT_BOUNDARY_IN_ROW: int = 2     # Mermaid's $c4BoundaryInRow default

  def compute_c4_positions(spec: GraphSpec, *, rank_sep: float = 80.0, node_sep: float = 40.0) -> LayoutResult:
      """Deterministic C4 placement (persons first tier, internal elements grouped in nested boundary
      boxes, external elements last tier). Same contract as ``compute_positions``; ``reversed_edges`` is
      always empty. Raises ``GraphTooLargeError`` above ``MAX_STATIC_NODES``."""

  def _tier_of(node: GraphNode) -> int: ...
  def _boundary_tree(spec: GraphSpec) -> dict[Optional[str], list[GraphGroup]]:
      """Children keyed by parent id (``None`` = top level), preserving ``groups[]`` order."""
  def _footprint(group_id: Optional[str], members: list[str], children: dict[Optional[str], list[GraphGroup]],
                 shape_in_row: int, depth: int) -> tuple[int, int]:
      """Bottom-up (slots wide, slots high) of a boundary including its padding and children."""
  def _place(...) -> dict[str, tuple[int, int]]:
      """Integer (rank_slot, cross_slot) per node id — the only place that walks the tree top-down."""
  ```
  ```python
  # packages/ai-parrot/src/parrot/outputs/a2ui/graph/layout.py  (modifies layout.py:228-290 and :337-348)
  def compute_positions(spec: GraphSpec, *, rank_sep: float = 80.0, node_sep: float = 40.0) -> LayoutResult:   # verified: layout.py:228
      """… + ``spec.kind == "c4"`` delegates to :func:`layout_c4.compute_c4_positions` AFTER the size cap
      check (:251-253) and BEFORE ``_break_cycles`` (:258); function-local import (layout_c4 imports this module)."""

  def _group_boxes(spec: GraphSpec, positions: dict[str, Position]) -> dict[str, tuple[float, float, float, float]]:  # verified: layout.py:337
      """… now nested-aware: a group's box is the padded union of its members' positions and its child
      groups' boxes (children resolved first); groups with neither are skipped (unchanged)."""
  ```

### Module 4: Catalog — lowering, instructions, authoring notes, utterances — `catalog/viz_core/graph.py`
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/viz_core/graph.py` (MODIFY); `packages/ai-parrot/tests/outputs/a2ui/golden/graph_c4_lowered.json` (CREATE, produced by the task)
- **Responsibility**: C4 branch of `lower()` (tree fixed in §2 Data Models), one added sentence in `GRAPH_INSTRUCTIONS`, the two FEAT-755 hand-off constants. `GRAPH_SCHEMA` needs no edit (derived).
- **Depends on**: Modules 1, 2 (`to_mermaid` for the `graph-source` node).
- **Decided content**:
  - `GRAPH_INSTRUCTIONS` += `" For a software-architecture diagram set kind=\"c4\" with level (context/container/component/dynamic), give every node a c4Type (person, system, container, component, *_ext, *_db, *_queue) plus technology/description, and model boundaries as groups (c4Type enterprise/system/container, nested via parent)."`
  - `GRAPH_C4_AUTHORING_NOTES`: a short, numbered authoring guide (one element per real system/container, externals as `*_ext`, persons first, every relationship labelled with a verb phrase, technology on containers/components, ≤ 15 elements per diagram, boundaries only when ≥ 2 members, never positions/`action`). Plain text, no colour vocabulary.
  - `GRAPH_C4_UTTERANCES` (EN/ES, mirrors the `DEFAULT_OUTPUT_MODE_ROUTES` style, `bots/data.py:297`): `"C4 context diagram of the platform"`, `"draw a C4 container diagram of this system"`, `"show the architecture as a C4 diagram"`, `"component diagram of the API service"`, `"system context diagram with external systems"`, `"diagrama de contexto C4 de la plataforma"`, `"diagrama de contenedores de la aplicación"`, `"dibuja la arquitectura del sistema como C4"`, `"diagrama de componentes del servicio"`, `"diagrama de contexto con los sistemas externos"`.
  - `lower()` for `kind == "c4"`: as fixed in §2 Data Models; the `edge-list` node keeps today's `_edge_extensions` plus `parrot_technology` when set; every non-C4 kind takes exactly today's code path.
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # packages/ai-parrot/src/parrot/outputs/a2ui/catalog/viz_core/graph.py  (modifies graph.py:42-51, :54-60, :76-153)
  from typing import Any, Final

  GRAPH_INSTRUCTIONS = (...)                                   # verified: graph.py:42 — one sentence appended
  GRAPH_C4_AUTHORING_NOTES: Final[str] = (...)
  GRAPH_C4_UTTERANCES: Final[tuple[str, ...]] = (...)

  def _edge_extensions(edge: GraphEdge) -> dict[str, Any]:     # verified: graph.py:54 — adds parrot_technology when edge.technology
      ...

  def _c4_children(spec: GraphSpec) -> list[BasicNode]:
      """Boundary-list and element-list Columns for a kind="c4" spec (order and roles per spec §2 Data Models)."""

  @register_component("Graph", catalog_id=VIZ_CORE_CATALOG_ID)  # verified: graph.py:63 (unchanged)
  class GraphComponent:                                         # verified: graph.py:64
      SCHEMA = GRAPH_SCHEMA
      INSTRUCTIONS = GRAPH_INSTRUCTIONS
      def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:   # verified: graph.py:76
          """… + kind == "c4": caption "C4 <level> diagram", boundary-list, element-list before the edge list;
          Card extensions gain parrot_c4_level. Non-C4 output is byte-identical to today."""
  ```

### Module 5: Builder — `build_graph(level=)` + `build_c4_diagram`
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py` (MODIFY)
- **Responsibility**: pass `level` into `GraphSpec`; provide the C4 convenience builder (keyword-only, TOOL origin default, `boundaries=` → `groups=`, `surface_id="c4-diagram"`); `__all__` entry.
- **Depends on**: Modules 1, 3 (`compute_positions` already called at `builders.py:436` resolves C4 via dispatch).
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # packages/ai-parrot/src/parrot/outputs/a2ui/builders.py  (modifies builders.py:43-54 import, :57-68 __all__, :330-348 signature, :414-425 GraphSpec(...))
  from parrot.outputs.a2ui.graph import C4Level, ...            # verified: builders.py:43-54 (existing import block)

  def build_graph(*, ..., selection: GraphSelection | dict[str, Any] | None = None,
                  level: C4Level | None = None, ...) -> CreateSurface:        # verified: builders.py:330 (level added after selection, :341)
      """… level: ``GraphSpec.level`` — required when ``kind="c4"`` (validated by the model)."""

  def build_c4_diagram(*, level: C4Level, nodes, edges, boundaries=None, direction: Direction = "TB",
                       title=None, accessible_description=None, size: VizSize = "tile", layout=None,
                       selection=None, data_binding=None, data_model=None, action: Action | None = None,
                       compute_layout: bool = True, surface_id: str = "c4-diagram",
                       origin: ProducerOrigin = ProducerOrigin.TOOL) -> CreateSurface:
      """Build a viz-core ``Graph`` envelope with ``kind="c4"``. Thin wrapper over :func:`build_graph`
      (``groups=boundaries``); every validation, layout and origin rule is ``build_graph``'s."""
  ```

### Module 6: Bundled UI — `A2UIGraph.svelte` + `A2UIGraph.test.ts`
- **Path**: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIGraph.svelte` (MODIFY), `A2UIGraph.test.ts` (MODIFY)
- **Responsibility**: wire types for the new fields; C4 path in the pure `buildGraphOption`; boundary frames; vitest coverage. `A2UINode.svelte` dispatch (`:167`, `:243-249`) is untouched.
- **Depends on**: Module 1 (wire shape only — can start as soon as §2 Data Models is frozen).
- **Decided rules**: `kind === 'c4'` ⇒ (a) node `symbol` from `c4SymbolFor`: `person*` → `'circle'` with caption `Person`; `*_db` → `'roundRect'` caption `[DB]`; `*_queue` → `'rect'` caption `[Queue]`; other → `'rect'` caption `''`; `external === c4Type.endsWith('_ext')` ⇒ `itemStyle.borderType: 'dashed'`; (b) `label.formatter` = `label` + `\n[technology]` when set; tooltip = label, `c4Type`, technology, description, then `meta` lines (reusing `tooltipText`, `:116`); (c) edges: `bidirectional` ⇒ `symbol: ['arrow', 'arrow']`, label `"<label> [<technology>]"`; `hint` ignored; (d) frames: `computeBoundaryFrames` mirrors `_group_boxes` (member positions ∪ child frames, padding 20 × depth, nested via `parent`), emitted as `option.graphic` rect + text elements ONLY when `hasCompletePositions` (`:106`) is true — the circular fallback shows no frames; (e) status role / `STATE_TO_STATUS` (`:80`) and `onNodeClick` (`:206`) unchanged; (f) non-C4 output of `buildGraphOption` byte-identical to today (existing five tests, `A2UIGraph.test.ts:11,53,69,81,93`, keep passing unchanged).
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```ts
  // packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIGraph.svelte  (<script module>, modifies :14-76 types, :131-194 buildGraphOption)
  export type C4Level = 'context' | 'container' | 'component' | 'dynamic';
  export type C4ElementType = 'person' | 'person_ext' | 'system' | 'system_ext' | 'system_db' | 'system_db_ext'
    | 'system_queue' | 'system_queue_ext' | 'container' | 'container_ext' | 'container_db' | 'container_db_ext'
    | 'container_queue' | 'container_queue_ext' | 'component' | 'component_ext' | 'component_db'
    | 'component_db_ext' | 'component_queue' | 'component_queue_ext';
  export type C4BoundaryType = 'enterprise' | 'system' | 'container' | 'generic';
  export type RelHint = 'up' | 'down' | 'left' | 'right' | 'back' | 'neighbor' | 'back_neighbor';

  export interface GraphNodeProps { /* existing */ c4Type?: C4ElementType; technology?: string; description?: string }      // verified: :22
  export interface GraphEdgeProps { /* existing */ technology?: string; hint?: RelHint; bidirectional?: boolean }           // verified: :32
  export interface GraphGroupProps { /* existing */ parent?: string; c4Type?: C4BoundaryType }                              // verified: :40
  export interface GraphLayoutProps { /* existing */ shapeInRow?: number; boundaryInRow?: number }                           // verified: :51
  export interface GraphProperties { /* existing */ level?: C4Level }                                                        // verified: :65
  export interface BoundaryFrame { id: string; label: string; depth: number; x: number; y: number; w: number; h: number }

  /** ECharts symbol + caption + external flag for a C4 element type (table in spec §3 M6). */
  export function c4SymbolFor(c4Type: C4ElementType | undefined): { symbol: string; caption: string; external: boolean };
  /** Nested boundary frames from member positions (mirror of the backend's `_group_boxes`); [] unless positions are complete. */
  export function computeBoundaryFrames(properties: GraphProperties): BoundaryFrame[];
  /** Unchanged signature; `kind === 'c4'` adds symbols, captions, dashed externals, bidirectional arrows and `graphic` frames. */
  export function buildGraphOption(properties: GraphProperties, resolveColor?: (token: string) => string): Record<string, unknown>;  // verified: :131
  ```
  Vitest additions (`A2UIGraph.test.ts`, appended after `:93`): `renders c4 boundary frames from complete positions`, `nests child boundary frames inside their parent`, `maps c4 element types to symbols and captions`, `dashes external elements`, `adds technology as a second label line`, `draws bidirectional edges with two arrowheads`, `c4 without positions falls back to circular with no frames`, `non-c4 option is unchanged by the c4 path`.

### Module 7: Docs + conformance + fixtures
- **Path**: `docs/outputs/a2ui-v1.md` (MODIFY), `docs/frontend/agentdashboard-a2ui-reference.md` (MODIFY), `packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py` (MODIFY), `packages/ai-parrot/tests/outputs/a2ui/fixtures/c4_container_diagram.json` (CREATE)
- **Responsibility**: document the C4 kind next to the Graph section; prove a C4 envelope is conformant, round-trips through Mermaid and renders (or degrades with one recorded entry) on every registered satellite renderer — without changing those renderers.
- **Depends on**: Modules 1–5.
- **Decided content**:
  - `a2ui-v1.md`: new `### C4 architecture diagrams — kind="c4" (FEAT-754)` inserted immediately BEFORE `### Renderer matrix` (`:393`): vocabulary block, boundaries-as-groups rule, validator table V1–V5, lowering-role table (C4 rows), Mermaid C4 subset + lossy list, layout rules, renderer notes (bundled UI native; satellites draw generic nodes).
  - `agentdashboard-a2ui-reference.md` §5.4: C4 rows appended to the `Graph` prop table (`:628-638`) and one paragraph after the lowering note describing the bundled renderer's C4 behaviour.
  - Fixture `c4_container_diagram.json`: a `GraphSpec` dict (container level; 1 person, 1 `system_ext`, 1 `system_boundary` holding 3 containers incl. a `container_db`, 5 relationships, one `bidirectional`) used by M2/M3/M4 tests and by the conformance twin.
  - `test_all_emitters.py`: `class TestC4GraphConformance` (after `TestCatalogDefinitionIncludesGraph`, `:555`) with `test_build_c4_diagram_conformant` (`_assert_conformant` on the builder output), `test_c4_mermaid_roundtrip_byte_stable`, `test_c4_graph_renders_on_every_registered_renderer` (same loop/degradation assertions as `:501-553`).
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py  (modifies after :555)
  def _c4_envelope() -> CreateSurface:
      """build_c4_diagram(...) over fixtures/c4_container_diagram.json."""

  class TestC4GraphConformance:
      def test_build_c4_diagram_conformant(self) -> None: ...
      def test_c4_mermaid_roundtrip_byte_stable(self) -> None: ...
      @pytest.mark.asyncio
      async def test_c4_graph_renders_on_every_registered_renderer(self) -> None: ...
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_c4_requires_level_and_c4_type` | M1 (`graph/test_models_c4.py`) | `kind="c4"` without `level`, or with a node lacking `c4Type`, raises `ValidationError` (V1) |
| `test_c4_fields_rejected_on_other_kinds` | M1 | `level`, node `c4Type`, edge `hint`/`bidirectional`, group `parent`/`c4Type`, `shapeInRow` on a flowchart raise (V2); `technology`/`description` are accepted on any kind |
| `test_group_parent_must_exist_and_be_acyclic` | M1 | unknown parent, self-parent, and an A→B→A chain raise (V3); duplicate group ids raise |
| `test_shape_in_row_and_boundary_in_row_together` | M1 | one without the other raises (V4); `ge=1` enforced |
| `test_dynamic_rejects_hint_and_bidirectional` | M1 | V5 |
| `test_c4_node_state_and_action_still_work` | M1 | a C4 node with `state="failed"` validates; `build_c4_diagram(action=...)` with TOOL origin validates, LLM origin is rejected by `ACTION_NOT_ALLOWED_FOR_LLM` |
| `test_no_forbidden_field_names_on_any_graph_model` (existing, `graph/test_models.py:155`) | M1 | still passes with the new fields |
| `test_c4_roundtrip_container_level_byte_stable` | M2 (`graph/test_mermaid_c4.py`) | fixture → `to_mermaid` → `from_mermaid` → `to_mermaid` is byte-identical; object-equal modulo `C4_LOSSY_FIELDS` |
| `test_c4_roundtrip_each_level_header` | M2 | context/container/component/dynamic headers map both ways |
| `test_c4_all_twenty_element_macros` | M2 | each `C4ElementType` emits its macro and parses back |
| `test_c4_nested_boundaries` | M2 | enterprise ⊃ system ⊃ container boundaries emit nested blocks with 4-space indents and parse back with `parent` set |
| `test_c4_rel_macros_and_birel` | M2 | every `(bidirectional, hint)` combination emits the right macro; spelled aliases parse |
| `test_c4_dynamic_relindex_ordering` | M2 | `RelIndex` emitted 1-based in `edges[]` order; out-of-order text parses back sorted; gaps/duplicates raise |
| `test_c4_update_layout_config` | M2 | emitted only when both counts set; parsed into `shapeInRow`/`boundaryInRow` |
| `test_c4_rejects_styling_sprites_and_deployment` | M2 | `UpdateElementStyle`, `UpdateRelStyle`, `$sprite=`, `$tags=`, `$link=`, `Deployment_Node` raise `MermaidCodecError` naming the line |
| `test_c4_quotes_and_unescapes_labels` | M2 | `"` and commas inside labels survive the round trip (`#quot;`, quoted args) |
| `test_c4_error_is_catalog_validation_error` | M2 | `MermaidCodecError` subclass contract unchanged (`mermaid.py:126`) |
| `test_generic_dispatch_to_c4` | M2 | `to_mermaid(c4 spec)` / `from_mermaid("C4Context…")` route through the generic pair; flowchart/state/sequence fixtures (`graph/test_mermaid.py`) unchanged |
| `test_c4_layout_deterministic` | M3 (`graph/test_layout_c4.py`) | two calls, equal `LayoutResult` |
| `test_c4_persons_first_tier_externals_last` | M3 | tier ordering on the rank axis for TB and LR (LR == transposed TB) |
| `test_c4_boundaries_nested_boxes_contain_members` | M3 | every member inside its box; child box inside parent box; boxes of siblings do not overlap |
| `test_c4_shape_in_row_wraps` | M3 | 6 containers with `shapeInRow=3` form two rows; defaults 4/2 when unset |
| `test_c4_reversed_edges_empty_and_cap` | M3 | `reversed_edges == []`; `GraphTooLargeError` above the cap |
| `test_group_boxes_nested_for_any_kind` | M3 | `_group_boxes` unions child groups (unit test via a c4 spec; flowchart behaviour unchanged — `graph/test_layout.py:83` still passes) |
| `test_graph_c4_lower_golden` | M4 (`test_components_graph_c4.py`) | deterministic, byte-equal to `golden/graph_c4_lowered.json` |
| `test_graph_c4_lower_roles_and_order` | M4 | description, title?, caption, boundary-list, element-list, edge-list, graph-source in that order; only Basic primitives (`to_components`) |
| `test_graph_c4_lower_source_is_c4_mermaid` | M4 | `graph-source` text starts with `C4Container` |
| `test_graph_lower_golden` (existing, `test_components_graph.py:51`) | M4 | non-C4 golden byte-identical |
| `test_graph_schema_has_all_spec_fields` / `test_graph_schema_has_no_colour_vocabulary` (existing, `test_catalog_parity.py:64,77`) | M4 | new aliases present; no styling vocabulary |
| `test_graph_c4_authoring_notes_and_utterances` | M4 | constants exported, non-empty, EN and ES present, no colour vocabulary |
| `test_graph_instructions_mention_c4` | M4 | `GRAPH_INSTRUCTIONS` contains `kind="c4"`; `catalog_instructions([VIZ_CORE_CATALOG_ID])` includes it |
| `test_build_c4_diagram_fills_positions_and_catalog_id` | M5 (`test_builders_c4.py`) | positions for every node, `catalogId == VIZ_CORE_CATALOG_ID`, `kind == "c4"`, `level` on the wire |
| `test_build_graph_level_passthrough` | M5 | `build_graph(kind="c4", level=...)` equals `build_c4_diagram(...)` output modulo `surface_id` |
| `test_build_c4_diagram_in_all` | M5 | `"build_c4_diagram" in builders.__all__` |
| `test_build_c4_diagram_action_tool_origin_only` | M5 | LLM origin + action rejected |
| vitest names listed in §3 M6 | M6 (`A2UIGraph.test.ts`) | C4 option building; existing five tests unchanged |

### Integration Tests
| Test | Description |
|---|---|
| `TestC4GraphConformance::test_build_c4_diagram_conformant` | builder output validates against the catalog allowlist and the lowered Basic wire schema (`_assert_conformant`) |
| `TestC4GraphConformance::test_c4_mermaid_roundtrip_byte_stable` | fixture envelope props → `GraphSpec` → Mermaid → `GraphSpec` → Mermaid, byte-stable |
| `TestC4GraphConformance::test_c4_graph_renders_on_every_registered_renderer` | SSR-HTML, interactive-HTML and ECharts render a C4 envelope natively (no exception, nodes present); adaptive-cards and folium record exactly one `degraded` entry — satellite renderers UNMODIFIED |
| `TestGraphRendersOnEveryRegisteredRenderer` / `TestFlowToGraphToMermaidRoundtrip` (existing, `test_all_emitters.py:501,466`) | unchanged behaviour for non-C4 graphs |
| `test_graph_svg_*` (existing, ai-parrot-visualizations `test_graph_svg.py`) | the static SVG lane still renders every existing fixture; regression gate for the shared `_group_boxes`/`compute_positions` changes |

### Validation Contract

> FEAT-699. Explicit pytest operands (repo-relative file or `file::node`) that gate this feature in ALL
> tiers — task, merge, feature (`/sdd-done`) and QA. When present it REPLACES the heuristic breadth
> (import impact, suite escalation); the nightly workflow covers everything else. Write
> `none — fallback` to opt out explicitly (bounded fallback: tasks' own tests + direct importers).
> Never list `real_llm` tests. `integration`/`e2e`-marked operands listed here DO run.
> `/sdd-task` caches this list into the per-spec index header (`test_contract`).

runners:
- kind: pytest
  tests:
  - packages/ai-parrot/tests/outputs/a2ui/graph/test_models.py
  - packages/ai-parrot/tests/outputs/a2ui/graph/test_mermaid.py
  - packages/ai-parrot/tests/outputs/a2ui/graph/test_layout.py
  - packages/ai-parrot/tests/outputs/a2ui/graph/test_models_c4.py
  - packages/ai-parrot/tests/outputs/a2ui/graph/test_mermaid_c4.py
  - packages/ai-parrot/tests/outputs/a2ui/graph/test_layout_c4.py
  - packages/ai-parrot/tests/outputs/a2ui/test_components_graph.py
  - packages/ai-parrot/tests/outputs/a2ui/test_components_graph_c4.py
  - packages/ai-parrot/tests/outputs/a2ui/test_builders_graph.py
  - packages/ai-parrot/tests/outputs/a2ui/test_builders_c4.py
  - packages/ai-parrot/tests/outputs/a2ui/test_catalog_parity.py
  - packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py
  - packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_graph_svg.py
  - packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_echarts_graph.py
  markers: none
- kind: vitest
  cwd: packages/ai-parrot-server/ui
  tests:
  - src/lib/components/agents/canvas/a2ui/A2UIGraph.test.ts

> The five `*_c4.py` files are CREATED by M1–M5; the rest exist today (paths verified at `b9417f4a0`).
> The two `ai-parrot-visualizations` files are regression gates only — this feature edits nothing in that package;
> run them with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-visualizations/src` inside the worktree.

### Test Data / Fixtures
```python
# packages/ai-parrot/tests/outputs/a2ui/fixtures/c4_container_diagram.json  (CREATE — the ONE shared C4 fixture)
{
  "kind": "c4", "level": "container", "title": "Order platform — containers",
  "accessibleDescription": "Customers use the web app, which calls the API; the API stores orders in Postgres and notifies the payment provider.",
  "nodes": [
    {"id": "customer", "label": "Customer", "c4Type": "person", "description": "Places orders"},
    {"id": "web", "label": "Web App", "c4Type": "container", "technology": "SvelteKit", "description": "Storefront UI"},
    {"id": "api", "label": "Order API", "c4Type": "container", "technology": "aiohttp", "description": "Order lifecycle", "state": "running"},
    {"id": "db", "label": "Orders DB", "c4Type": "container_db", "technology": "PostgreSQL"},
    {"id": "payments", "label": "Payment Provider", "c4Type": "system_ext", "description": "Card processing"}
  ],
  "edges": [
    {"from": "customer", "to": "web", "label": "Uses", "technology": "HTTPS"},
    {"from": "web", "to": "api", "label": "Calls", "technology": "JSON/HTTPS"},
    {"from": "api", "to": "db", "label": "Reads/writes", "technology": "asyncpg", "bidirectional": true},
    {"from": "api", "to": "payments", "label": "Charges", "technology": "REST"},
    {"from": "payments", "to": "api", "label": "Webhook", "technology": "HTTPS", "hint": "back"}
  ],
  "groups": [{"id": "platform", "label": "Order Platform", "c4Type": "system", "nodes": ["web", "api", "db"]}]
}

# tests/outputs/a2ui/graph/conftest.py does not exist and is NOT created: each new test module loads the
# fixture with json.loads(Path(...).read_text()) exactly like conformance/test_all_emitters.py:472 does for
# dev_loop_flow.json.  `golden/graph_c4_lowered.json` is produced by the M4 task (`_dump(...)` helper pattern,
# test_components_graph.py:18-19) and committed with it.
```

### E2E Scenarios

> Optional (FEAT-581) — only for a feature that exercises the deterministic
> E2E gate (`parrot e2e run` / `parrot e2e verify`). Omit this whole
> subsection, and the frontmatter `e2e` key above, for a feature with no E2E
> surface; an absent policy defaults to `optional` once a plan is loaded.

Not applicable — this feature has no E2E surface (pure models, codec, layout, builder, lowering and a
unit-tested Svelte option builder). No `e2e` frontmatter key is declared.

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `GraphKind` accepts `"c4"`; `GraphSpec`/`GraphNode`/`GraphEdge`/`GraphGroup`/`GraphLayout` carry exactly the fields of §2 Data Models with the aliases `c4Type`, `shapeInRow`, `boundaryInRow`; validators V1–V5 raise `ValidationError` with the documented messages.
- [ ] `GRAPH_SCHEMA` contains `level`, `shapeInRow`, `boundaryInRow` and the nested `c4Type`/`technology`/`description`/`hint`/`bidirectional`/`parent` properties WITHOUT any edit to `GRAPH_SCHEMA` itself (derived); `test_graph_schema_has_all_spec_fields` and `test_graph_schema_has_no_colour_vocabulary` pass.
- [ ] `to_mermaid(spec)` for the shared fixture emits `C4Container` source using only the macros listed in §3 M2; `from_mermaid` parses it back; the round trip is byte-stable and object-equal modulo `C4_LOSSY_FIELDS`; every rejected construct raises `MermaidCodecError` naming its line.
- [ ] `compute_positions(c4 spec)` is deterministic, places persons on the first tier and `*_ext` elements on the last, returns a `group_boxes` entry for every boundary (nested boxes contain their children), `reversed_edges == []`, and honours `MAX_STATIC_NODES`; `_group_boxes` for flowchart groups is unchanged (`graph/test_layout.py` passes untouched).
- [ ] `build_c4_diagram(...)` returns a validated `CreateSurface` whose root `Graph` carries `catalogId == VIZ_CORE_CATALOG_ID`, `kind == "c4"`, `level`, and complete `layout.positions`; `build_graph(level=...)` is equivalent; `"build_c4_diagram" in builders.__all__`.
- [ ] `GraphComponent.lower()` of a C4 graph yields the tree of §2 Data Models (golden `graph_c4_lowered.json`); `golden/graph_lowered.json` is byte-identical to today.
- [ ] `GRAPH_INSTRUCTIONS` mentions `kind="c4"`; `GRAPH_C4_AUTHORING_NOTES` and `GRAPH_C4_UTTERANCES` (EN + ES) are exported from `catalog/viz_core/graph.py`; no router, emitter or `DEFAULT_OUTPUT_MODE_ROUTES` change.
- [ ] `A2UIGraph.svelte` renders `kind="c4"` with boundary frames (when positions are complete), per-type symbols/captions, technology label lines, dashed externals and bidirectional arrows; the eight new vitest cases pass and the five existing ones are unchanged; `pnpm build` succeeds.
- [ ] `TestC4GraphConformance` passes: the C4 envelope is conformant, round-trips, and renders/degrades on every registered satellite renderer with ZERO changes under `packages/ai-parrot-visualizations/`.
- [ ] Every operand in the Validation Contract passes in the feature worktree; `ruff check` and `black --check` clean on touched Python files.
- [ ] `docs/outputs/a2ui-v1.md` and `docs/frontend/agentdashboard-a2ui-reference.md` document the C4 kind (sections of §3 M7); no new dependency in any `pyproject.toml` or `package.json`.
- [ ] No breaking change: every existing `GraphSpec`, envelope, Mermaid text and renderer test passes unchanged; new fields are optional with `None` defaults.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> Verified against `b9417f4a0` (dev, 2026-10-27). Core source root is `packages/ai-parrot/src/parrot/`.

### Verified Imports
```python
from parrot.outputs.a2ui.graph import (                         # verified: graph/__init__.py:11-28
    MAX_STATIC_NODES, GraphTooLargeError, LayoutResult, compute_positions,          # :11
    MermaidCodecError, from_mermaid, to_mermaid,                                    # :12
    Direction, EdgeKind, GraphEdge, GraphGroup, GraphKind, GraphLayout, GraphNode,  # :14-20
    GraphSelection, GraphSpec, LayoutEngine, NodeShape, NodeState, Position, VizSize,  # :21-27
)
from parrot.outputs.a2ui.graph.models import GraphKind, GraphNode, GraphEdge, GraphGroup, Position, GraphLayout, GraphSelection, GraphSpec  # verified: models.py:47,57,87,110,127,141,165,179
from parrot.outputs.a2ui.graph.mermaid import MermaidCodecError, to_mermaid, from_mermaid        # verified: mermaid.py:126,206,323
from parrot.outputs.a2ui.graph.mermaid import _escape_label, _unescape_label, _prepare_lines, _check_unsupported, _IDENT  # verified: mermaid.py:146,153,174,163,109 (private, same package — M2 reuses them)
from parrot.outputs.a2ui.graph.layout import MAX_STATIC_NODES, GraphTooLargeError, LayoutResult, compute_positions, _group_boxes, _extent, _oriented_position, _GROUP_PADDING, _LAYOUT_PADDING  # verified: layout.py:60,68,85,228,337,310,293,64,65
from parrot.outputs.a2ui.catalog import register_component, get_component, unregister_component, catalog_instructions, validate_envelope, ProducerOrigin, DEFAULT_CATALOG_ID  # verified: catalog/__init__.py:114,209,196,314,743; re-exported names used at builders.py:37-41
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree, CatalogValidationError, ACTION_NOT_ALLOWED_FOR_LLM, to_components  # verified: catalog/base.py:111,171,317,78,174
from parrot.outputs.a2ui.catalog.parrot._derive import derive_schema                           # verified: catalog/parrot/_derive.py:88
from parrot.outputs.a2ui.catalog.viz_core import VIZ_CORE_CATALOG_ID, VIZ_CORE_INSTRUCTIONS      # verified: catalog/viz_core/__init__.py:28,35
from parrot.outputs.a2ui.catalog.viz_core import graph as graph_mod                              # verified: catalog/viz_core/__init__.py:75; test_catalog_parity.py:19
from parrot.outputs.a2ui.catalog.viz_core.graph import GRAPH_SCHEMA, GRAPH_INSTRUCTIONS, GraphComponent  # verified: graph.py:35,42,64
from parrot.outputs.a2ui.builders import build_graph, build_surface                             # verified: builders.py:330,79
from parrot.outputs.a2ui.models import Action, Component, ComponentMetadata, CreateSurface, Extensions, SurfaceMetadata  # verified: builders.py:55 (import line)
from parrot.outputs.a2ui.adapters.flow import flow_definition_to_graph                          # verified: adapters/flow.py:63 (NOT modified; listed so no task "adds C4" there)
import networkx as nx                                                                            # verified: layout.py:46; core dependency pyproject.toml:193 — NOT needed by layout_c4
from parrot.models.outputs import OutputMode                                                     # verified: models/outputs.py:23; OutputMode.A2UI = "a2ui" at :55 (context only — not imported by any module here)
# ai-parrot-visualizations (regression only, never edited):
from parrot.outputs.a2ui_renderers._graph_svg import STATE_TO_STATUS, render_graph_svg          # verified: packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/_graph_svg.py:29,75
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py
GraphKind = Literal["flowchart", "state", "sequence", "dag"]                    # line 47
Direction = Literal["TB", "LR", "BT", "RL"]                                     # line 48
NodeShape = Literal["rect", "rounded", "diamond", "circle", "hexagon", "subroutine"]  # line 49
NodeState = Literal["pending", "running", "completed", "failed", "skipped", "waiting"]  # line 50
EdgeKind = Literal["solid", "dashed", "thick"]                                  # line 51
LayoutEngine = Literal["layered", "force", "manual"]                            # line 52
VizSize = Literal["inline", "tile", "hero"]                                     # line 54
class GraphNode(BaseModel):          # line 57; model_config = ConfigDict(extra="forbid")  line 76
    id: str; label: Optional[str]; shape: Optional[NodeShape]; group: Optional[str]; state: Optional[NodeState]; icon: Optional[str]; meta: Optional[dict[str, Any]]  # lines 78-84
class GraphEdge(BaseModel):          # line 87; ConfigDict(extra="forbid", populate_by_name=True)  line 101
    from_: str = Field(alias="from"); to: str; label: Optional[str]; kind: Optional[EdgeKind]; condition: Optional[str]  # lines 103-107
class GraphGroup(BaseModel):         # line 110; ConfigDict(extra="forbid")  line 120  (no populate_by_name today)
    id: str; label: Optional[str]; nodes: list[str]                              # lines 122-124
class Position(BaseModel):           # line 127;  x: float; y: float            # lines 137-138
class GraphLayout(BaseModel):        # line 141; ConfigDict(extra="forbid", populate_by_name=True)  line 157
    engine: LayoutEngine = "layered"; rank_sep (alias rankSep); node_sep (alias nodeSep); positions: Optional[dict[str, Position]]  # lines 159-162
class GraphSelection(BaseModel):     # line 165;  selectable: bool = False; selected: Optional[str]  # lines 175-176
class GraphSpec(BaseModel):          # line 179; ConfigDict(extra="forbid", populate_by_name=True)  line 214
    kind: GraphKind = "flowchart"; direction: Direction = "TB"; title; accessible_description (alias accessibleDescription); size: VizSize = "tile";
    nodes: list[GraphNode]; edges: list[GraphEdge]; groups: Optional[list[GraphGroup]]; layout: Optional[GraphLayout]; selection: Optional[GraphSelection];
    data: Optional[dict[str, dict[str, Any]]]                                   # lines 216-226
    @model_validator(mode="after") def _validate_graph(self) -> GraphSpec       # line 229 (groups check 257-268, dag 270-271, manual 273-279, `return self` 281)
    def _has_cycle(self) -> bool                                                # line 283 (iterative 3-colour DFS)

# packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py
_UNSUPPORTED_PREFIXES = ("classDef", "click", "style", "linkStyle", "loop", "alt", "par", "note", "Note")  # lines 77-87
_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"                                              # line 109
class MermaidCodecError(CatalogValidationError): def __init__(self, line_no: int, line: str, reason: str)  # lines 126-143
def _escape_label(label: str) -> str                                            # line 146  ('"' → '#quot;', quotes when reserved chars present)
def _unescape_label(token: Optional[str]) -> Optional[str]                      # line 153
def _check_unsupported(line_no: int, content: str) -> None                      # line 163
def _prepare_lines(text: str) -> list[tuple[int, str]]                          # line 174  (drops blanks/`%%`, rejects `%%{`)
def to_mermaid(spec: GraphSpec) -> str                                          # line 206; dispatch `if spec.kind == "sequence":` 218, state 220, flowchart/dag 224
def from_mermaid(text: str) -> GraphSpec                                        # line 323; header dispatch 344-349; `raise MermaidCodecError(... "unrecognized or unsupported diagram header")` 350
def _parse_flowchart(...)  # line 397 — rejects nested subgraph at 426 (reason: "nested 'subgraph' is not supported")

# packages/ai-parrot/src/parrot/outputs/a2ui/graph/layout.py
MAX_STATIC_NODES = 200                                                          # line 60
_GROUP_PADDING = 20.0; _LAYOUT_PADDING = 20.0                                   # lines 64-65
class GraphTooLargeError(CatalogValidationError): def __init__(self, node_count: int)  # lines 68-82
class LayoutResult(BaseModel): positions: dict[str, Position]; width: float; height: float; group_boxes: dict[str, tuple[float, float, float, float]]; reversed_edges: list[tuple[str, str]]  # lines 85-107
def _break_cycles(node_ids, edge_pairs) -> tuple[list, list]                    # line 110
def _assign_ranks(node_ids, dag_edges) -> dict[str, int]                        # line 166 (networkx topological_sort, 168-178)
def _order_within_ranks(node_ids, rank, dag_edges) -> dict[int, list[str]]      # line 181
def compute_positions(spec: GraphSpec, *, rank_sep: float = 80.0, node_sep: float = 40.0) -> LayoutResult  # lines 228-290 (cap 251-253; `_break_cycles` call 258)
def _oriented_position(rank_coord: float, cross_coord: float, direction: Direction) -> Position  # line 293
def _extent(positions, max_rank, rank_sep, node_sep, direction, by_rank) -> tuple[float, float]  # line 310 (BT/RL mirroring)
def _group_boxes(spec: GraphSpec, positions: dict[str, Position]) -> dict[str, tuple[float, float, float, float]]  # lines 337-348 (skips a group with no member positions, 341-342)

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/viz_core/graph.py
GRAPH_SCHEMA: dict[str, Any] = derive_schema(GraphSpec, binding_fields=("data",), required=("nodes", "edges"))  # lines 35-39; action $ref merge line 40
GRAPH_INSTRUCTIONS = (...)                                                      # lines 42-51
def _edge_extensions(edge: GraphEdge) -> dict[str, Any]                         # lines 54-60 (parrot_role="edge", parrot_edge_kind, parrot_condition)
@register_component("Graph", catalog_id=VIZ_CORE_CATALOG_ID) class GraphComponent  # lines 63-64; SCHEMA 73; INSTRUCTIONS 74
    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree  # line 76 (graph_props 95, GraphSpec.model_validate 96, description 98-100, children 102-108, title 109-112, caption 113-119, edge list 121-138, source 140-146, Card 148-153)

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/viz_core/__init__.py
VIZ_CORE_CATALOG_ID: Final[str] = "https://ai-parrot.dev/a2ui/catalogs/viz-core/1.0/catalog.json"  # line 28
from parrot.outputs.a2ui.catalog.viz_core import graph  # noqa: E402,F401      # line 75 (registration side effect)

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py
def register_component(name: str, *, requires_actions: bool = False, catalog_id: str = DEFAULT_CATALOG_ID, is_primitive: bool = False, allowed_parents=None, allowed_children=None, tool_only: bool = False) -> Callable[[type], type]  # lines 114-122
def unregister_component(name: str, catalog_id: str = DEFAULT_CATALOG_ID) -> None   # line 196
def get_component(name: str, catalog_id: str | None = None) -> RegisteredComponent  # line 209
def catalog_instructions(catalog_ids: Sequence[str] | None = None) -> str            # line 314
def validate_envelope(envelope, *, origin: ProducerOrigin = ProducerOrigin.TOOL, surface_catalog_id: str | None = None) -> None  # lines 743-748

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py
DEFAULT_CATALOG_ID = "https://parrot.dev/catalogs/v1"   # line 53;  ACTION_NOT_ALLOWED_FOR_LLM  line 78;  class ProducerOrigin(str, Enum)  line 99
class BasicNode(BaseModel)  # line 111 (extra="allow"; nested child/children);  BasicTree = BasicNode  line 171;  def to_components(tree, *, id_prefix="blk")  line 174
class ComponentDefinition(BaseModel)  # line 234 — fields name, catalog_id, schema_ (alias "schema"), instructions, requires_actions, is_primitive, allowed_parents, allowed_children, tool_only
class CatalogError(Exception)  # line 305;  class CatalogValidationError(CatalogError)  # line 317 (code / issues)

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/_derive.py
def derive_schema(model: type[BaseModel], *, binding_fields: Sequence[str], required: Sequence[str] = ()) -> dict[str, Any]  # lines 88-93 (model_json_schema(by_alias=True); strips titles; keeps $defs; camelCases TOP-LEVEL names only — nested models rely on Field aliases)

# packages/ai-parrot/src/parrot/outputs/a2ui/builders.py
from parrot.outputs.a2ui.graph import (Direction, GraphEdge, GraphGroup, GraphKind, GraphLayout, GraphNode, GraphSelection, GraphSpec, VizSize, compute_positions)  # lines 43-54
__all__ = ["build_card", "build_chart", "build_datatable", "build_graph", "build_html_document", "build_infographic", "build_kpicard", "build_linked_surface", "build_map", "build_surface"]  # lines 57-68
def _binding(pointer: str | None) -> dict[str, str] | None                      # line 76
def build_surface(component: str, properties: dict[str, Any], *, surface_id: str, component_id: str = "root", data_model=None, origin: ProducerOrigin = ProducerOrigin.LLM, metadata=None, surface_metadata=None) -> CreateSurface  # lines 79-89
def build_graph(*, nodes, edges, kind: GraphKind = "flowchart", direction: Direction = "TB", title=None, accessible_description=None, size: VizSize = "tile", groups=None, layout=None, selection=None, data_binding=None, data_model=None, action: Action | None = None, compute_layout: bool = True, surface_id: str = "graph", origin: ProducerOrigin = ProducerOrigin.TOOL) -> CreateSurface  # lines 330-348
    # body: _model() 403-406; GraphSpec(...) 414-425; compute_layout block 427-438 (compute_positions call 436); props/catalogId 440-441; binding 443-445; action 446-447; build_surface("Graph", ...) 449-455

# packages/ai-parrot/src/parrot/outputs/a2ui/adapters/flow.py
def flow_definition_to_graph(definition: Mapping[str, Any], *, kind: GraphKind = "flowchart", direction: Direction = "TB", data_binding: str | None = None) -> GraphSpec  # lines 63-69 (untouched)

# packages/ai-parrot/src/parrot/bots/data.py
DEFAULT_OUTPUT_MODE_ROUTES: Dict[str, List[str]] = {OutputMode.STRUCTURED_CHART.value: [...], STRUCTURED_TABLE: [...], STRUCTURED_MAP: [...]}  # line 297 (EN/ES utterance style M4 mirrors; NOT edited — FEAT-755 owns it)

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/  (regression only — never edited)
_graph_svg.py: STATE_TO_STATUS: dict[str, str]  line 29;  def render_graph_svg(props: dict[str, Any], *, theme: str | None = None) -> str  line 75;  _render_group_box(group, box)  line 200
echarts.py:    _GRAPH_INTERCEPT_TABLE  line 52;  def _build_graph_option(self, props: dict[str, Any]) -> dict[str, Any]  line 396
interactive_html.py: `if name == "Graph": return self._render_graph(comp, degradations)`  lines 1036-1037;  force-layout / GraphTooLargeError degradation 1700-1726

# packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIGraph.svelte  (<script module>)
export type GraphNodeState  lines 14-20;  export interface GraphNodeProps  22-30;  GraphEdgeProps  32-38;  GraphGroupProps  40-44;  GraphPosition  46-49;  GraphLayoutProps  51-56;  GraphSelectionProps  58-61;  GraphProperties  65-76
export const STATE_TO_STATUS  80-87;  STATUS_ORDER  89;  STATUS_TO_TOKEN  95-101
export function hasCompletePositions(properties: GraphProperties): boolean  106-110;  statusForNode  112;  tooltipText  116
export function buildGraphOption(properties: GraphProperties, resolveColor: (token: string) => string = (token) => token): Record<string, unknown>  131-134 (usePositions 135; edge lineStyle 168-169; categories 187)
<script lang="ts">: interface Props { properties; dataModel?; onNodeClick? }  200-207;  let { properties }: Props = $props()  213;  resolveColor  218;  option = $derived(buildGraphOption(...))  229;  markup 240-246
# A2UINode.svelte: import type { GraphProperties }  line 12;  import A2UIGraph  18;  isVizCoreGraph  167;  dispatch  243-249  (untouched)
# A2UIGraph.test.ts: imports 5-6 (`buildGraphOption, hasCompletePositions, type GraphProperties`);  describe  10;  tests  11, 53, 69, 81, 93
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `GraphSpec.level` / node `c4_type` … (M1) | `GraphSpec._validate_graph()` | validators appended before `return self` | `graph/models.py:229,281` |
| `C4Level` … re-exports (M1) | `parrot.outputs.a2ui.graph.__all__` | re-export list | `graph/__init__.py:13-28,30-52` |
| `to_mermaid_c4` / `from_mermaid_c4` (M2) | `to_mermaid()` / `from_mermaid()` | kind / header dispatch (function-local import) | `graph/mermaid.py:218,344-350` |
| `MermaidCodecError` reuse (M2) | `CatalogValidationError` | subclass (unchanged) | `graph/mermaid.py:126`, `catalog/base.py:317` |
| `compute_c4_positions` (M3) | `compute_positions()` | kind dispatch after the cap check | `graph/layout.py:251-258` |
| nested `_group_boxes` (M3) | `LayoutResult.group_boxes` | same return shape | `graph/layout.py:106,337` |
| `GRAPH_SCHEMA` new properties (M4) | `derive_schema(GraphSpec, …)` | automatic (by_alias) | `catalog/viz_core/graph.py:35-39`, `_derive.py:88` |
| `lower()` C4 branch (M4) | `BasicNode` / `to_mermaid` | Basic primitives + source text | `catalog/viz_core/graph.py:76-153`, `catalog/base.py:111` |
| `GRAPH_C4_AUTHORING_NOTES` / `GRAPH_C4_UTTERANCES` (M4) | FEAT-755 emitter / phrase bank | module constants (consumer not in this repo state) | `sdd/proposals/output-mode-intent-router.brainstorm.md:162,271` |
| `build_c4_diagram` (M5) | `build_graph()` → `build_surface()` → `validate_envelope()` | delegation | `builders.py:330,449-455,79` |
| `build_graph(level=)` (M5) | `GraphSpec(...)` construction | one keyword | `builders.py:414-425` |
| `buildGraphOption` C4 path (M6) | `A2UINode.svelte` dispatch | unchanged props contract | `A2UINode.svelte:167,249` |
| `TestC4GraphConformance` (M7) | `_assert_conformant`, renderer loop | same helpers as the existing Graph sweep | `conformance/test_all_emitters.py:501-553` |

### Does NOT Exist (Anti-Hallucination)
Searched at `b9417f4a0` across `packages/ai-parrot/src`, `packages/ai-parrot-server/ui/src`, `packages/ai-parrot-visualizations/src`, `packages/ai-parrot/tests` (0 files for each):
- ~~`parrot.outputs.a2ui.graph.mermaid_c4`~~, ~~`to_mermaid_c4`~~, ~~`from_mermaid_c4`~~ — created by M2.
- ~~`parrot.outputs.a2ui.graph.layout_c4`~~, ~~`compute_c4_positions`~~ — created by M3.
- ~~`build_c4_diagram`~~ — created by M5; ~~`parrot.outputs.a2ui.__init__` exporting `build_graph`~~ — `a2ui/__init__.py` exports NO builders (verified: no `build_` name in it), so M5 adds nothing there.
- ~~`C4Level`~~, ~~`C4ElementType`~~, ~~`C4BoundaryType`~~, ~~`RelHint`~~, ~~`GraphNode.c4_type`/`c4Type`~~, ~~`GraphGroup.parent`~~, ~~`GraphLayout.shape_in_row`/`boundary_in_row`~~, ~~`GraphSpec.level`~~ — created by M1.
- ~~`GRAPH_C4_AUTHORING_NOTES`~~, ~~`GRAPH_C4_UTTERANCES`~~, ~~any `authoring_notes` / `AUTHORING_NOTES` attribute on a catalog component or `ComponentDefinition`~~ — M4 adds the two module constants; no registry slot exists (`ComponentDefinition` fields are listed above; FEAT-755 decides the lookup contract — §8 Q1).
- ~~`MermaidDiagram` component~~ (FEAT-753) and ~~`sdd/specs/inline-a2ui-component-routing.spec.md`~~ (FEAT-755) — neither exists yet; only `sdd/proposals/output-mode-intent-router.brainstorm.md` references them.
- ~~`GraphSpec.boundaries`~~ — boundaries ARE `groups`; no separate field is introduced.
- ~~`GraphLayout.group_boxes` on the wire~~ — boxes are computed (`LayoutResult.group_boxes` server-side; `computeBoundaryFrames` in the UI); never serialized.
- ~~a `Graph` entry in `catalog/viz_core/spec/catalog.json`~~ — the vendored viz-core draft defines only `Chart`, `Series`, `Stat`; there is no drift guard to update for Graph/C4.
- ~~`tests/outputs/a2ui/graph/conftest.py`~~ — only `tests/outputs/a2ui/conftest.py` (`v1_schemas` fixture) exists; new tests load the JSON fixture directly.
- ~~`OutputMode.STRUCTURED_C4` / `OutputMode.C4`~~ — no per-component `OutputMode` members are added (brainstorm rev 2 rule: `OutputMode.A2UI` + component hint).
- ~~`networkx` in `layout_c4.py`~~ — not imported there; the C4 rules are tier/grid based.
- ~~`GraphGroup.model_config.populate_by_name`~~ — today `ConfigDict(extra="forbid")` only (`models.py:120`); M1 adds `populate_by_name=True` because `c4_type` gets an alias.

### Edit Sites (Blueprint Anchors)

Verified against: `b9417f4a0` (2026-10-27). `/sdd-task` MUST re-run the `grep -c` for every row it uses.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py` | MODIFY | `GraphKind = Literal["flowchart", "state", "sequence", "dag"]` | `models.py:47` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py` | MODIFY | `    "VizSize",` (end of `__all__`) | `models.py:44` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py` | MODIFY | `    meta: Optional[dict[str, Any]] = None` (last `GraphNode` field) | `models.py:84` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py` | MODIFY | `    condition: Optional[str] = None` (last `GraphEdge` field) | `models.py:107` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py` | MODIFY | `    nodes: list[str]` (last `GraphGroup` field) | `models.py:124` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py` | MODIFY | `    positions: Optional[dict[str, Position]] = None` (last `GraphLayout` field) | `models.py:162` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py` | MODIFY | `    data: Optional[dict[str, dict[str, Any]]] = None` (last `GraphSpec` field) | `models.py:226` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py` | MODIFY | `        if self.kind == "dag" and self._has_cycle():` (V1–V5 inserted after the manual-positions block that follows it) | `models.py:270` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/__init__.py` | MODIFY | `from .mermaid import MermaidCodecError, from_mermaid, to_mermaid` | `__init__.py:12` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid_c4.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py` | MODIFY | `    if spec.kind == "sequence":` (C4 branch inserted before it) | `mermaid.py:218` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py` | MODIFY | `    raise MermaidCodecError(header_no, header, "unrecognized or unsupported diagram header")` (`C4` header branch inserted before it) | `mermaid.py:350` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/layout_c4.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/layout.py` | MODIFY | `    dag_edges, reversed_edges = _break_cycles(node_ids, edge_pairs)` (C4 dispatch inserted before it) | `layout.py:258` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/layout.py` | MODIFY | `def _group_boxes(spec: GraphSpec, positions: dict[str, Position]) -> dict[str, tuple[float, float, float, float]]:` | `layout.py:337` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/viz_core/graph.py` | MODIFY | `GRAPH_INSTRUCTIONS = (` | `graph.py:42` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/viz_core/graph.py` | MODIFY | `                text=f"Graph ({spec.kind}, {spec.direction})",` (caption; C4 branch forks here) | `graph.py:116` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py` | MODIFY | `    "build_graph",` (`__all__`) | `builders.py:61` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py` | MODIFY | `    selection: GraphSelection | dict[str, Any] | None = None,` (`level` keyword inserted after it) | `builders.py:341` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py` | MODIFY | `        selection=selection_model,` (`level=level,` inserted after it) | `builders.py:424` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIGraph.svelte` | MODIFY | `  export interface GraphNodeProps {` | `A2UIGraph.svelte:22` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIGraph.svelte` | MODIFY | `    const usePositions = hasCompletePositions(properties);` | `A2UIGraph.svelte:135` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIGraph.test.ts` | MODIFY | `  it('represents node group membership', () => {` (new cases appended after this test) | `A2UIGraph.test.ts:93` | 1 |
| `packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py` | MODIFY | `class TestCatalogDefinitionIncludesGraph:` (new class inserted after it) | `test_all_emitters.py:555` | 1 |
| `packages/ai-parrot/tests/outputs/a2ui/fixtures/c4_container_diagram.json` | CREATE | — | — | — |
| `packages/ai-parrot/tests/outputs/a2ui/golden/graph_c4_lowered.json` | CREATE | — | — | — |
| `packages/ai-parrot/tests/outputs/a2ui/graph/test_models_c4.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/outputs/a2ui/graph/test_mermaid_c4.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/outputs/a2ui/graph/test_layout_c4.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/outputs/a2ui/test_components_graph_c4.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/outputs/a2ui/test_builders_c4.py` | CREATE | — | — | — |
| `docs/outputs/a2ui-v1.md` | MODIFY | `### Renderer matrix` (C4 subsection inserted before it) | `a2ui-v1.md:393` | 1 |
| `docs/frontend/agentdashboard-a2ui-reference.md` | MODIFY | `` #### `Graph` (`catalog/viz_core/graph.py`) — required `nodes`, `edges` `` | `agentdashboard-a2ui-reference.md:626` | 1 |

- A **CREATE** row declares only the path the module adds; it needs no anchor.
- **Occurrences > 1** means the one-line anchor is ambiguous. Quote 2–3 lines of
  surrounding context in the anchor cell so the blueprint block can attach uniquely.
- An anchor that cannot be verified is written `(unverified — check before use)`,
  never guessed.

---

## 7. Implementation Notes & Constraints

> Architecture decisions stay with the thinking model. A delegated
> implementation may only express a decision already recorded here and in
> the TASK's implementation blocks — it must never invent an API, choose a
> file, or resolve an open design question.

### Patterns to Follow
- **`GraphSpec` stays the single vocabulary** (`models.py:1-22` docstring). No module introduces a parallel C4 shape — the codec, layout, lowering and UI all read the same fields. `GRAPH_SCHEMA` is never hand-edited (`graph.py:11`).
- **What, never how** (viz-core principle). `shapeInRow`/`boundaryInRow` are counts; `c4Type` is semantics; the glyph/caption/dash mapping lives in the renderers (M6) and is DOCUMENTED (`docs/outputs/a2ui-v1.md`), never modelled. Add no `Field(description=...)` whose text contains colour/font words — the parity regex scans the whole schema blob (`test_catalog_parity.py:81-86`).
- **Fail closed on vocabulary mismatch** (V2, V5). A C4-only field on a flowchart is a validation error, not a silently dropped field — the same philosophy as `MermaidCodecError` for unsupported constructs.
- **Function-local imports for the two dispatches** (`mermaid.py` → `mermaid_c4.py`, `layout.py` → `layout_c4.py`) with a one-line comment explaining the import direction. Everything else is a top-level import.
- **Codec conventions reused verbatim**: `_escape_label`/`_unescape_label` (`#quot;`), label collapsing when equal to `id` (`mermaid.py:38-40`), `%%` comment handling via `_prepare_lines`, line-addressed `MermaidCodecError`s, trailing newline on emission, input-preserving order.
- **Layout conventions reused verbatim**: integer slot arithmetic scaled at the end, `_GROUP_PADDING`/`_LAYOUT_PADDING`, `_extent` for BT/RL mirroring, `logger.debug` summary line (`layout.py:277-282`), the cap check first.
- **Lowering conventions reused verbatim**: `parrot_role` extensions, `Card{Column[...]}` root with `parrot_variant: "graph"`, `parrot_graph_data` pass-through (`graph.py:129-131`), `to_mermaid(spec)` as the last child. New golden produced with the `_dump` helper (`test_components_graph.py:18-19`, `sort_keys=True, indent=2`).
- **Builder conventions**: keyword-only, `_model()` coercion (`builders.py:403-406`), `catalogId` override (`:441`), TOOL origin default with the D10b gate untouched.
- **Svelte 5 runes only**, pure logic in `<script module>` so vitest needs no DOM (`A2UIGraph.svelte:1-12` comment), no new npm dependency (no mermaid/dagre/elkjs), match surrounding formatting (no prettier step).
- **Tests**: run with `PYTHONPATH=packages/ai-parrot/src` (plus `packages/ai-parrot-visualizations/src` for the two regression files) inside the worktree; `ruff check --fix` + `black` (line length 120) on touched Python files; `pnpm vitest run src/lib/components/agents/canvas/a2ui/A2UIGraph.test.ts` in `packages/ai-parrot-server/ui`.

### Known Risks / Gotchas
- **Node-order canonicalisation on C4 round trip.** C4 syntax declares elements inside their boundary block, so `from_mermaid(to_mermaid(spec))` returns nodes in canonical order (ungrouped first, then per boundary). Mitigation: the fixture and all round-trip tests use canonical order; the module docstring states the rule; `C4_LOSSY_FIELDS` + the order rule define the "modulo" set explicitly. Byte-stability of the TEXT holds regardless.
- **`_group_boxes` becomes nested-aware for every kind.** A flowchart with `groups` is unaffected (no `parent` ⇒ identical arithmetic), but the function is shared with `_graph_svg._compute_group_boxes`'s caller path through `compute_positions`. Mitigation: `graph/test_layout.py::TestLayoutGroupBoxesContainMembers` and `test_graph_svg.py::TestGraphSvgGroupBoxes` are in the Validation Contract.
- **Duplicate group ids now rejected (V3).** Previously unvalidated and nonsensical (two `subgraph` blocks with one id); no fixture or golden in the repo has duplicates (checked: `dev_loop_flow.json` has no groups; `graph_lowered.json` has none). Recorded as a deliberate tightening.
- **`GraphGroup` gains `populate_by_name=True`.** Needed for the `c4Type` alias; harmless for existing constructors (`GraphGroup(id=…, nodes=…)` and `GraphGroup(**wire_dict)` both keep working).
- **Satellite renderers draw C4 as generic nodes.** `render_graph_svg` and the ECharts renderer show labels/positions/status roles only — no glyphs, no technology, no frames beyond the existing group boxes (which DO now include nested boundaries via `_group_boxes`). Documented in the renderer matrix; a follow-up spec may add glyphs there.
- **Mermaid C4 is marked experimental upstream.** Macro names/arities here follow the Mermaid C4 syntax reference as of the spec date; the parser is strict on arity to surface drift as `MermaidCodecError` rather than mis-parse. If Mermaid adds args, extend the arity table (one dict) — §8 Q4.
- **`UpdateLayoutConfig` takes both counts.** Modelled as "both or none" (V4) to keep the round trip exact; a caller wanting only `shapeInRow` sets `boundaryInRow` to the default `2` explicitly.
- **`RelIndex` for Dynamic diagrams.** Mermaid `C4Dynamic` also accepts plain `Rel`; the codec EMITS `RelIndex` only (sequence is the point of a dynamic diagram) and PARSES both (plain `Rel` lines in a `C4Dynamic` keep text order and are numbered after any indexed ones). V5 forbids hints/bidirectional there so nothing is silently lost.
- **UI frames need complete positions.** With the ECharts circular fallback there is nowhere to put a frame; `computeBoundaryFrames` returns `[]` and the diagram still shows nodes, captions and dashed externals — degradation is visible but not broken. `build_c4_diagram` always fills positions, so the normal path has frames.
- **FEAT-755 contract is not frozen.** `GRAPH_C4_AUTHORING_NOTES`/`GRAPH_C4_UTTERANCES` are module constants with no registry slot; if FEAT-755 standardises a class attribute (e.g. on the component class) the M4 task adds a one-line alias — no other module depends on the name (§8 Q1).
- **Parallel sessions on this repo.** FEAT-753/755/752/756 are being specified in the same window; this spec touches `graph/`, `catalog/viz_core/graph.py`, `builders.py` and `A2UIGraph.svelte` — FEAT-755 is expected to touch `builders.py`/`catalog/*` for the emitter. Keep the `builders.py` diff to the three anchored lines + one new function so the merge is mechanical.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| — | — | None added. `pydantic` v2 (existing), `networkx>=3.0` (existing core dep, `pyproject.toml:193`, used by `layout.py` only), ECharts (existing UI dep). No Mermaid/dagre/elkjs/PlantUML package anywhere. |

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [ ] **Q1 — Authoring-notes lookup contract.** Where should FEAT-755's catalog-driven emitter find per-component authoring notes: a module constant (this spec's `GRAPH_C4_AUTHORING_NOTES`), a `GraphComponent.AUTHORING_NOTES` class attribute, or a new `ComponentDefinition.authoring_notes` field registered via `register_component`? This spec ships the module constant; whichever FEAT-755 chooses, M4 adds the alias in the same file. — *Owner: Jesus Lara (decide in the FEAT-755 spec)*
- [ ] **Q2 — Phrase-bank key for the C4 intent.** FEAT-755 rev 2 routes on `a2ui:<Component>` labels. Should C4 be a distinct label (`a2ui:Graph:c4`) so the emitter receives `kind="c4"` as a hint, or share `a2ui:Graph` and let the authoring notes steer the LLM? `GRAPH_C4_UTTERANCES` is kept separate from any generic Graph utterances so either choice works. — *Owner: Jesus Lara (FEAT-755)*
- [ ] **Q3 — `GraphGroup.parent` for non-C4 kinds.** This feature restricts `parent` to `kind="c4"` (V2) so the flowchart/state codecs never meet a nested group (they reject nested `subgraph`/composite states today, `mermaid.py:426,506`). Lift the restriction together with nested-subgraph codec support in a follow-up? — *Owner: Jesus Lara*
- [ ] **Q4 — Mermaid C4 macro arity drift.** Should the parser accept and IGNORE unknown trailing positional args (forward-compatible) instead of raising? Current decision: raise (strict, consistent with the other dialects). — *Owner: Jesus Lara*
- [ ] **Q5 — Tier for external persons.** `person_ext` is placed on tier 0 with internal persons (actors first) rather than tier 2 with other externals. Confirm after seeing the fixture rendered. — *Owner: Jesus Lara (M3 task review)*
- [ ] **Q6 — Satellite glyphs.** Should a follow-up add C4 glyphs/technology captions to `_graph_svg.py` (static/PDF lanes) and `echarts.py`? Not in scope here (Non-Goals); flagging so it is not forgotten. — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

Status: skipped (no accepted exploration document — spec authored from the NAV-10382 ticket review)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

---

## Worktree Strategy

- **Isolation**: ONE feature worktree `feat-FEAT-754-a2ui-c4-diagrams` (from `origin/dev`, via `python -m scripts.sdd.ensure_worktree --slug a2ui-c4-diagrams --feature-id FEAT-754`); the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (edges = imports/uses, evidence in §3): M2 → M1; M3 → M1; M4 → M1, M2 (`to_mermaid`); M5 → M1, M3 (through `compute_positions` dispatch); M6 → M1 (wire shape only); M7 → M1–M5 (conformance) and M6 (docs paragraph). **M1 first, alone, its own commit.** Then M2 ‖ M3 ‖ M6 concurrently (disjoint files); M4 after M2; M5 after M3; M7 last.
- **Shared files** (tasks serialized): `graph/__init__.py` (M1 adds the Literals; M2 and M3 each add their re-export line — M2's and M3's edits are one line each and may be folded into their own tasks, never into M1); `graph/mermaid.py` (M2 only); `graph/layout.py` (M3 only); `catalog/viz_core/graph.py` (M4 only); `builders.py` (M5 only); `conformance/test_all_emitters.py` (M7 only).
- **Exclusive resources** (`parallel: false`): none — no lockfile, no generated UI types (`A2UIGraph.svelte` declares its own types; `src/lib/types/generated/` is untouched), no `.so` rebuild.
- **Cross-feature dependencies**: builder / codec / layout / lowering / renderer lanes have NONE — FEAT-529 is merged on `dev`. The LLM authoring lane depends on FEAT-755 landing its (a) hint channel + emitter FIRST; this spec only publishes the constants FEAT-755 consumes, so the two features merge in either order without conflict as long as `builders.py` edits stay at the anchored lines. FEAT-753 may call `to_mermaid()` on a C4 spec once this merges; nothing here waits for it.
- **Tests inside the worktree**: `PYTHONPATH=packages/ai-parrot/src pytest <Validation Contract operands> -q`; add `:packages/ai-parrot-visualizations/src` for the two regression files; `cd packages/ai-parrot-server/ui && pnpm vitest run src/lib/components/agents/canvas/a2ui/A2UIGraph.test.ts`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-27 | Jesus Lara | Initial draft from the NAV-10382 review (FEAT-754 reserved); verified against `b9417f4a0` |
