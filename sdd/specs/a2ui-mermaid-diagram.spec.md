---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot, ai-parrot-tools, ai-parrot-visualizations, ai-parrot-server, admin-ui, docs]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [a2ui, mermaid, diagrams, parrot-catalog, inline-widgets, renderers]
# e2e: optional deterministic-E2E-gate policy metadata (FEAT-581). Absent
#   entirely (the default for every spec written before this feature) means
#   the generated e2e-plan.md's policy defaults to `optional` when loaded.
#   `policy` MUST be exactly `required`, `optional` or `none` — an
#   unrecognized value fails plan loading closed, it is never coerced to a
#   default. `scenario_ids` are the plan's stable `ScenarioSpec.id` values,
#   kept in sync with the "### E2E Scenarios" subsection below (§4). Omit
#   this whole key for a feature with no E2E surface.
# e2e:
#   policy: optional
#   scenario_ids: []
---

# Feature Specification: A2UI `MermaidDiagram` — opaque Mermaid-source component in the Parrot catalog

**Feature ID**: FEAT-753
**Date**: 2026-10-27
**Author**: Jesus Lara
**Status**: draft
**Target version**: TBD
**Origin**: NAV-10382 review (2026-10-27) — "mermaid" is on the follow-up list of inline-renderable artifacts; no accepted brainstorm/proposal (spec authored from the ticket review + codebase research)
**Sibling specs (same NAV-10382 follow-up batch)**: FEAT-755 `inline-a2ui-component-routing` (LLM authoring route, **not yet written**; its source is `sdd/proposals/output-mode-intent-router.brainstorm.md` rev 2), FEAT-754 `a2ui-c4-diagrams` (typed C4, not yet written), FEAT-752 `followup-suggestion-chips`, FEAT-756 `metric-definition-registry`

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

An inline chat answer in ai-parrot can be routed, from the user's phrasing, to exactly
three structured shapes — `structured_chart` / `structured_table` / `structured_map`
(FEAT-224 phrase bank `DEFAULT_OUTPUT_MODE_ROUTES`, `packages/ai-parrot/src/parrot/bots/data.py:297`).
The NAV-10382 review lists **Mermaid diagrams** among the artifacts an inline bubble
should be able to show next: "sequence diagram of the login flow", "diagrama de
secuencia del checkout", "show the ER model as a diagram". Today there is no A2UI
component that can carry such an answer:

1. **`Graph` is typed, not Mermaid.** The viz-core `Graph` component (FEAT-529,
   `packages/ai-parrot/src/parrot/outputs/a2ui/graph/{models.py,mermaid.py,layout.py}`)
   puts TYPED `nodes[]`/`edges[]` on the wire and treats Mermaid as a pure-Python
   import/export codec for exactly three dialect subsets — `flowchart` (also used by
   `kind="dag"` on export), `stateDiagram-v2` and `sequenceDiagram` — and only the
   constructs listed in `graph/mermaid.py:1-56`. A class diagram, an ER diagram, a
   gantt chart, a pie, a mindmap, a gitGraph, a user journey or a C4 diagram cannot be
   expressed as a `GraphSpec` at all, and even a flowchart that uses `classDef`, a
   `loop`/`alt` block or a `note` raises `MermaidCodecError` (`graph/mermaid.py:77-87`,
   `:174-199`). The docs are explicit: "never a mermaid string on the wire"
   (`docs/outputs/a2ui-v1.md:280-283`) — correct for a *typed* workflow component, but
   it leaves the long tail of Mermaid diagram types with no home.
2. **No opaque-source precedent for diagrams.** `HtmlDocument`
   (`packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/htmldocument.py`) proves the
   pattern of an *opaque* surface — a trusted payload passed through, lowered to a
   titled placeholder, embedded natively only by a renderer that can do so safely — but
   it is `tool_only=True` because raw HTML must never be LLM-authorable. Mermaid source
   is a much smaller attack surface (a declarative text DSL) and *should* be LLM-authorable
   under a validation gate — that gate does not exist.
3. **Mermaid already appears in the codebase twice, unconnected.** The interactive-HTML
   tool catalog ships a `mermaid` CDN library card
   (`packages/ai-parrot/src/parrot/tools/interactive/catalog/libraries/mermaid.md`,
   mermaid 10.9.3 via jsDelivr) for the `interactive_*` HTML-authoring lane, and the Graph
   codec's edge-operator scan was rewritten to dodge a CodeQL Mermaid false positive
   (commit `34339ee3f`, `graph/mermaid.py:107,445`). Neither gives an A2UI consumer a
   component to dispatch on.
4. **Every renderer needs a deterministic degradation.** Teams (Adaptive Cards), Telegram,
   A2A `DataPart`s, SSR-HTML/PDF and the interactive-HTML lane cannot run mermaid.js. An
   inline diagram must still show *something readable and copyable* there — the same
   rule `Graph` follows with its lowered edge list + mermaid source
   (`docs/outputs/a2ui-v1.md:340-354`).

**Affected:** agents answering architecture / process / data-model questions inline;
the bundled `ai-parrot-server/ui` reference renderer (`canvas/a2ui/A2UINode.svelte`);
navigator-frontend-next (consumer — out of scope, wire contract documented); FEAT-755,
which needs a registered component + schema + authoring notes to route to.

### Goals

- **G1 — One opaque, display-only Parrot-catalog component `MermaidDiagram`** carrying
  Mermaid *source* for every diagram type mermaid.js supports (`sequence`, `class`, `er`,
  `gantt`, `pie`, `journey`, `mindmap`, `gitGraph`, `flowchart`, `state`, `c4`, …):
  `source` (required), `diagramType` (detected enum + `"unknown"`), optional `title`,
  `caption`, `theme` hint and `accessibleDescription`; `requires_actions=False`,
  `tool_only=False` (LLM-authorable under G2); registered under
  `DEFAULT_CATALOG_ID` like every Parrot composite.
- **G2 — Validation and safety on every origin.** A size cap on `source`;
  `%%{init: …}%%` / `%%{initialize …}%%` directives are a *builder-side normalization*
  (stripped, `theme` lifted into the prop) and **never** a wire feature — any directive
  surviving to `validate_envelope` is rejected; `click` / `link` / `callback`
  interaction statements, `javascript:` URLs and `<script` fragments are rejected; a
  declared `diagramType` that disagrees with the detected one is rejected. Every
  envelope validates against the catalog allowlist AND, lowered, against the vendored
  Basic wire schema (`tests/outputs/a2ui/conformance/test_all_emitters.py` two-layer
  pattern).
- **G3 — Readable lowering everywhere.** `lower()` → `Card{Column[description Text,
  title Text?, caption Text?, source Text(parrot_role: "mermaid-source")]}`; every
  satellite renderer and transport without a Mermaid engine shows the title and the
  source as a monospace code block and records ONE `degraded` entry (never raises).
- **G4 — Keep `MermaidDiagram` opaque; make the bridge to `Graph` explicit and opt-in.**
  One function converts a `MermaidDiagram` source to a typed `GraphSpec` *when* it
  parses with the existing `from_mermaid` codec (flowchart / stateDiagram-v2 /
  sequenceDiagram subset); nothing converts automatically. `to_mermaid(spec)` output is
  always a valid `MermaidDiagram.source` (round-trip test).
- **G5 — Deterministic producers.** `builders.build_mermaid_diagram(...) -> CreateSurface`
  (pure, validated) and a tool-facing `MermaidDiagramTool` (`render_mermaid_diagram`)
  in `parrot_tools`, whose dict result the bot lifts into `response.a2ui_envelope`
  through the existing FEAT-611 dict-result lift, generalized to a second artifact type.
- **G6 — LLM authoring hands off to FEAT-755.** This spec registers the component's
  JSON schema + `INSTRUCTIONS` (what the catalog-schema-driven emitter consumes) and
  exposes the default EN/ES route utterances as a constant FEAT-755's phrase bank
  imports; it builds **no** router/emitter machinery.
- **G7 — Reference renderer.** The bundled `ai-parrot-server/ui` SPA renders
  `MermaidDiagram` inline with mermaid.js **lazily imported** (same `await import(...)`
  idiom as `ECharts.svelte:110` / `DataMap.svelte:124`), `securityLevel: "strict"`,
  `startOnLoad: false`, SVG sanitized with the already-installed `dompurify` before
  `{@html}`, and a code-block fallback on parse/render error. The server-side
  interactive-HTML lane does **not** embed mermaid.js (see §2 Overview, decision D5).

### Non-Goals (explicitly out of scope)

- A typed C4 model / `Graph.kind="c4"` — **FEAT-754**. A C4 diagram written in Mermaid's
  `C4Context`/`C4Container`/… dialect IS accepted here as opaque source
  (`diagramType: "c4"`), which is exactly the degradation path FEAT-754 can later upgrade.
- The composite route key `a2ui:<Component>`, the router changes, the catalog-schema-driven
  LLM emitter, per-agent/per-tenant phrase banks — **FEAT-755**. Here: schema +
  instructions + a utterance constant only.
- Follow-up suggestion chips (FEAT-752), the metric definition registry (FEAT-756).
- **Any server-side Mermaid rendering** (no headless browser, no `mermaid-cli`, no
  Python Mermaid parser). The Python side validates text; it never draws.
- Extending the `Graph` codec (`graph/mermaid.py`) to more dialects or constructs.
  `from_mermaid`'s subset is unchanged; the opt-in conversion simply reuses it.
- Bundling mermaid.js into the server-side interactive-HTML artifact (FEAT-493
  self-contained invariant: "zero external network references", vendored Chart.js only —
  `a2ui_renderers/interactive_html.py:3-9`; the FEAT-197 CSP builder
  `handlers/csp.py` allows CDN origins only through the infographic `JSBundle` allowlist).
- navigator-frontend-next changes (the wire contract is documented in
  `docs/frontend/agentdashboard-a2ui-reference.md`; the frontend team implements it).
- Changing `HtmlDocument`, `Graph`, or the viz-core catalog.

---

## 2. Architectural Design

### Overview

`MermaidDiagram` is the second *opaque* Parrot-catalog component after `HtmlDocument`,
but with the opposite trust posture: Mermaid source is a declarative text DSL, so the
component is **LLM-authorable** (not `tool_only`) and the safety work moves into a
**pure, line-based source check** that runs inside `validate_envelope` for every origin.
Rendering is a renderer concern, exactly as for `HtmlDocument`/`Graph`: Python never
draws; it validates, normalizes, lowers and documents.

Decisions carried from the NAV-10382 review and refined by the research:

- **D1 — Catalog placement.** `MermaidDiagram` registers under `DEFAULT_CATALOG_ID`
  (`https://parrot.dev/catalogs/v1`), not viz-core. viz-core's rule is "describe what,
  never how" with typed vocabulary (`docs/outputs/a2ui-v1.md:102-123`); an opaque source
  string violates it by construction. Parrot is the presentation catalog that already
  hosts the opaque `HtmlDocument`. A bare `MermaidDiagram` therefore resolves on every
  Parrot-default surface with no per-component `catalogId`.
- **D2 — Hand-written `SCHEMA`** (like `HTMLDOCUMENT_SCHEMA`), not `derive_schema`: there
  is no config model to derive from and the shape is five scalar props.
- **D3 — Directives are never on the wire.** `normalize_mermaid_source()` (builder /
  tool lane) strips every `%%{ … }%%` directive, lifting a `theme` value into the `theme`
  prop; `check_mermaid_source()` (validation lane, every origin) rejects any directive
  that is still present. Rationale: mermaid.js's own `secure` list already blocks a
  directive from flipping `securityLevel`/`secure`/`startOnLoad`/`maxTextSize`, but
  `htmlLabels`, `flowchart.htmlLabels` and arbitrary theme CSS (`themeCSS`) are NOT in
  that list — stripping everything is simpler to reason about than an allowlist and
  costs nothing the LLM lane needs (the instructions say "never write a directive").
- **D4 — Interaction statements are rejected, not stripped.** `click`, `link`, `callback`
  (flowchart / class / gantt interaction syntax), any `javascript:` URL and any `<script`
  fragment fail validation with `MERMAID_UNSAFE_INTERACTION`. The LLM producer's existing
  validate-retry-degrade loop handles the re-prompt (same plumbing `MermaidCodecError`
  relies on, `graph/mermaid.py:126-131`).
- **D5 — The interactive-HTML lane falls back to the code block.** Embedding mermaid.js
  would break the renderer's self-contained invariant and require a CSP `script-src`
  CDN entry outside the infographic `JSBundle` mechanism. `SurfaceNegotiationService._respond_html`
  (`packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py:288-313`) serves the
  renderer's output verbatim; nothing there negotiates scripts. The lane therefore shows
  the lowered `<pre><code class="language-mermaid">` with a `degraded` record — a human
  can paste it into any Mermaid viewer. Revisit when/if a vendored mermaid bundle lands
  (§8 Q3).
- **D6 — Diagram-type detection is a pure function of the source** (first statement
  after YAML front-matter, `%%` comments and directives) and the wire `diagramType` is
  advisory-but-checked: the builder fills it, the validator recomputes it and rejects a
  mismatch, renderers never trust it over mermaid.js's own parser.
- **D7 — Bot lift generalization.** The FEAT-611 dict-result lift
  (`bots/base.py:1023-1045`) accepts `artifacts[].type == "a2ui_linked_surface"` only.
  The tool lane returns the same shape with `type: "a2ui_surface"`; the lift accepts both
  (one-line change, precedence rules untouched). FEAT-755 may later route its own output
  through the same lift.

### Component Diagram

```
                 ┌────────────────────────────── producers ───────────────────────────────┐
  LLM (FEAT-755) │ build_surface("MermaidDiagram", props, origin=LLM)  ← schema+INSTRUCTIONS│
  Tool / Python  │ build_mermaid_diagram(source, …) ──► normalize_mermaid_source ──► TOOL   │
  Agent tool     │ MermaidDiagramTool.render_mermaid_diagram ──► build_mermaid_diagram      │
                 └──────────────────────────────┬────────────────────────────────────────┘
                                                ▼
          catalog.validate_envelope ──► _validate_mermaid_sources ──► check_mermaid_source
          (every origin)                (size cap · no directive · no click/js · type match)
                                                ▼
                     CreateSurface{ components:[ {id:"root", component:"MermaidDiagram", source, diagramType, …} ] }
                                                │
            ┌───────────────────────────────────┼─────────────────────────────────────────┐
            ▼                                   ▼                                         ▼
  bundled UI A2UINode.svelte          MermaidDiagramComponent.lower()           graph_spec_from_mermaid_source
  ──► A2UIMermaidDiagram.svelte       Card{Column[description, title?,          (opt-in; flowchart/state/sequence
      lazy import('mermaid')            caption?, Text(parrot_role:             subset via from_mermaid) ──► GraphSpec
      securityLevel:'strict'            "mermaid-source")]}
      DOMPurify ──► {@html svg}               │
      error ──► <pre><code>        ┌──────────┼──────────────┬─────────────────┐
                                   ▼          ▼              ▼                 ▼
                              ssr_html/pdf  adaptive_cards  interactive-html  A2A / Telegram
                              <pre><code>   Monospace       <pre><code>       lowered text
                              + degraded    TextBlock       + degraded        (existing paths)
                                            + degraded
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `catalog.register_component` (`catalog/__init__.py:114`) | uses | `@register_component("MermaidDiagram", allowed_parents=["root", "Column"])` — defaults `requires_actions=False`, `tool_only=False`, `catalog_id=DEFAULT_CATALOG_ID` |
| `catalog.validate_envelope` (`catalog/__init__.py:743`) | extends | new pass `_validate_mermaid_sources(envelope, issues)` appended next to the linked-sources pass (`:964`); runs for BOTH origins |
| `catalog.base` error codes (`catalog/base.py:61-96`) | extends | four new codes after `TRANSFORM_REF_UNKNOWN` (`:96`) |
| `catalog/parrot/__init__.py:13-24` | extends | import `mermaiddiagram` for its registration side effect |
| `builders.build_surface` (`builders.py:79`) | uses | `build_mermaid_diagram` is a thin, validated wrapper like `build_html_document` (`:278`) |
| `graph.mermaid.from_mermaid` / `to_mermaid` / `MermaidCodecError` (`graph/mermaid.py:323,206,126`) | uses | opt-in conversion + round-trip guarantee; codec unchanged |
| `graph/__init__.py:30` `__all__` | extends | re-export `detect_diagram_type`, `normalize_mermaid_source`, `check_mermaid_source`, `graph_spec_from_mermaid_source`, `MERMAID_DIAGRAM_TYPES` |
| `AbstractTool` / `AbstractToolArgsSchema` (`parrot/tools/abstract.py:282,238`) | extends | `MermaidDiagramTool` mirrors `PublishSurfaceTool` (`parrot_tools/ui_surfaces.py:65`) |
| `parrot_tools/__init__.py:127` tool mapping | extends | `"mermaid_diagram": "parrot_tools.mermaid_diagram.MermaidDiagramTool"` |
| `AbstractBot._extract_last_linked_surface_result` (`bots/base.py:1023`) | extends | accept `artifacts[].type in {"a2ui_linked_surface", "a2ui_surface"}` (`:1042`) |
| `SSRHTMLRenderer._render_Text` (`a2ui_renderers/ssr_html.py:516`) | extends | `parrot_role == "mermaid-source"` → `<pre><code class="language-mermaid">` + `degradation_record` (PDF inherits) |
| `AdaptiveCardsRenderer` Text rendering (`a2ui_renderers/adaptive_cards.py:460-485`) | extends | same role → `TextBlock(fontType="Monospace", wrap=True)` + degradation |
| `InteractiveHTMLRenderer._render_prim_Text` (`a2ui_renderers/interactive_html.py:1117`) | extends | same role → `<pre><code>` + degradation; **not** added to `_INTERCEPTED` (`:136`) |
| `A2UINode.svelte` (`ui/.../canvas/a2ui/A2UINode.svelte:250`) | extends | new `{:else if component === 'MermaidDiagram'}` branch before the `HtmlDocument` branch |
| `ui/package.json:46` | extends | add the `mermaid` dependency (lazy-imported only) |
| `docs/outputs/a2ui-v1.md:78,474`, `docs/frontend/agentdashboard-a2ui-reference.md:497,582,616,710` | extends | catalog row, new component section, renderer matrix, §5.5 frontend contract |

### Data Models

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid_source.py  (new, pure)
MermaidDiagramType = Literal[
    "flowchart", "sequence", "class", "state", "er", "journey", "gantt", "pie",
    "quadrant", "requirement", "gitGraph", "c4", "mindmap", "timeline", "zenuml",
    "sankey", "xychart", "block", "packet", "kanban", "architecture", "radar",
    "treemap", "unknown",
]
MERMAID_DIAGRAM_TYPES: tuple[str, ...]          # the Literal's values, in that order
MERMAID_SOURCE_MAX_BYTES: Final[int] = 32_768   # UTF-8 bytes of `source` (HtmlDocument's inline guidance is "< 50 KB"; a diagram is smaller)
MERMAID_THEMES: tuple[str, ...] = ("default", "neutral", "dark", "forest", "base")

#: header keyword (first token of the first statement) -> diagram type
_HEADER_TO_TYPE: dict[str, str] = {
    "flowchart": "flowchart", "graph": "flowchart",
    "sequenceDiagram": "sequence",
    "classDiagram": "class", "classDiagram-v2": "class",
    "stateDiagram": "state", "stateDiagram-v2": "state",
    "erDiagram": "er", "journey": "journey", "gantt": "gantt", "pie": "pie",
    "quadrantChart": "quadrant", "requirementDiagram": "requirement", "gitGraph": "gitGraph",
    "C4Context": "c4", "C4Container": "c4", "C4Component": "c4", "C4Dynamic": "c4", "C4Deployment": "c4",
    "mindmap": "mindmap", "timeline": "timeline", "zenuml": "zenuml",
    "sankey-beta": "sankey", "xychart-beta": "xychart", "block-beta": "block",
    "packet-beta": "packet", "kanban": "kanban", "architecture-beta": "architecture",
    "radar-beta": "radar", "treemap-beta": "treemap",
}

class MermaidSourceIssue(TypedDict):
    code: str        # one of the four codes below (catalog/base.py)
    message: str
    line_no: int | None

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py  (appended after TRANSFORM_REF_UNKNOWN, :96)
MERMAID_SOURCE_TOO_LARGE = "MERMAID_SOURCE_TOO_LARGE"           # len(source.encode()) > MERMAID_SOURCE_MAX_BYTES, or empty
MERMAID_UNSAFE_DIRECTIVE = "MERMAID_UNSAFE_DIRECTIVE"           # a `%%{` directive line survived normalization
MERMAID_UNSAFE_INTERACTION = "MERMAID_UNSAFE_INTERACTION"       # click/link/callback statement, `javascript:` URL, `<script`
MERMAID_DIAGRAM_TYPE_MISMATCH = "MERMAID_DIAGRAM_TYPE_MISMATCH" # declared `diagramType` != detect_diagram_type(source)
```

**Wire schema** (`MERMAIDDIAGRAM_SCHEMA`, hand-written like `HTMLDOCUMENT_SCHEMA`
`htmldocument.py:24-49`; catalog props live top-level on the `Component`, never under
`properties`):

```json
{
  "type": "object",
  "properties": {
    "source": {"type": "string", "minLength": 1, "maxLength": 32768,
               "description": "Mermaid diagram source. No %%{init}%% directives, no click/link/callback statements."},
    "diagramType": {"type": "string",
                    "enum": ["flowchart","sequence","class","state","er","journey","gantt","pie","quadrant",
                             "requirement","gitGraph","c4","mindmap","timeline","zenuml","sankey","xychart",
                             "block","packet","kanban","architecture","radar","treemap","unknown"],
                    "description": "Detected from the first statement of `source`; a mismatch fails validation."},
    "title": {"type": "string"},
    "caption": {"type": "string"},
    "theme": {"type": "string", "enum": ["default", "neutral", "dark", "forest", "base"],
              "description": "Renderer hint only; the renderer may override it with the host theme."},
    "accessibleDescription": {"type": "string",
                              "description": "Screen-reader summary; first line of the lowered fallback."}
  },
  "required": ["source"]
}
```

**Lowered tree** (`MermaidDiagramComponent.lower()`), all Basic primitives, golden-tested:

| Order | Node | `metadata.extensions` |
|---|---|---|
| root | `Card{id=<component.id>}` → `Column` | `parrot_variant: "mermaid-diagram"` |
| 1 | `Text` — `accessibleDescription`, else generated `"Mermaid <diagramType> diagram"` | `parrot_role: "description"` |
| 2 | `Text` (if `title`) | `parrot_role: "title"` |
| 3 | `Text` (if `caption`) | `parrot_role: "caption"` |
| 4 | `Text` — the exact `source` | `parrot_role: "mermaid-source"`, `parrot_diagram_type: <diagramType>`, `parrot_mermaid_theme: <theme>` (only when set) |

`parrot_role: "mermaid-source"` is a NEW role (added to the `metadata.extensions`
table in `docs/outputs/a2ui-v1.md`); `Graph` keeps its own `"graph-source"` role
(`catalog/viz_core/graph.py:144`) — renderers treat the two identically (monospace
block) but the distinction preserves the "which component was this" signal.

**Tool result shape** (`MermaidDiagramTool._execute`, lifted by the bot per D7):

```json
{
  "a2ui_envelope": {"surfaceId": "mermaid-diagram", "catalogId": "https://parrot.dev/catalogs/v1", "components": [...], "dataModel": {}},
  "artifacts": [{"type": "a2ui_surface", "component": "MermaidDiagram", "surface_id": "mermaid-diagram", "diagram_type": "sequence"}],
  "diagram_type": "sequence",
  "source": "sequenceDiagram\n  A->>B: hi\n"
}
```

(`a2ui_envelope` is the BARE `CreateSurface` dump — `model_dump(by_alias=True, mode="json")` — exactly
like `qs_build_linked_surface`; `_wrap_create_surface` adds `version` at lift time,
`bots/base.py:1044`, `test_linked_surface_lifting.py:53`.)

### New Public Interfaces

```python
# parrot.outputs.a2ui.graph  (re-exported from graph/mermaid_source.py)
def detect_diagram_type(source: str) -> str: ...
def normalize_mermaid_source(source: str) -> tuple[str, str | None]: ...      # (source without directives, lifted theme or None)
def check_mermaid_source(source: str, *, declared_type: str | None = None) -> list[MermaidSourceIssue]: ...
def graph_spec_from_mermaid_source(source: str) -> GraphSpec: ...              # raises MermaidCodecError outside the subset
MERMAID_DIAGRAM_TYPES: tuple[str, ...]
MERMAID_SOURCE_MAX_BYTES: int
MERMAID_DIAGRAM_ROUTE_KEY: str = "a2ui:MermaidDiagram"                          # FEAT-755 decides the final key format (§8 Q1)
MERMAID_DIAGRAM_ROUTE_UTTERANCES: tuple[str, ...]                               # EN/ES default phrase-bank utterances

# parrot.outputs.a2ui.catalog.parrot.mermaiddiagram
MERMAIDDIAGRAM_SCHEMA: dict[str, Any]
MERMAIDDIAGRAM_INSTRUCTIONS: str
class MermaidDiagramComponent: SCHEMA, INSTRUCTIONS, lower(component, data_model) -> BasicTree

# parrot.outputs.a2ui.builders
def build_mermaid_diagram(*, source, title=None, caption=None, theme=None, accessible_description=None,
                          diagram_type=None, surface_id="mermaid-diagram", origin=ProducerOrigin.TOOL,
                          metadata=None) -> CreateSurface: ...

# parrot_tools.mermaid_diagram  (also reachable as parrot.tools.mermaid_diagram via the meta_path finder)
class MermaidDiagramArgs(AbstractToolArgsSchema): source, title, caption, theme, accessible_description
class MermaidDiagramTool(AbstractTool): name = "render_mermaid_diagram"
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
| M1: Mermaid source utilities + error codes | yes | pure functions, signatures below; header table, directive/interaction regexes, byte cap, four codes in `base.py`; no catalog import beyond `catalog.base` (same as `graph/mermaid.py:56`) | — |
| M2: `MermaidDiagram` catalog component + validation pass | yes | `HtmlDocument` file layout (`htmldocument.py`), schema/instructions text fixed in §2/§7, lowered tree fixed in §2, `_validate_mermaid_sources` placement fixed (`catalog/__init__.py:964`) | — |
| M3: Builder + `__all__` exports | yes | `build_html_document` shape (`builders.py:278-327`); normalization-then-validate order fixed | — |
| M4: Tool + registry mapping + bot lift | yes | `PublishSurfaceTool` shape (`ui_surfaces.py:35-168`); result dict fixed in §2; lift change is one membership test (`bots/base.py:1042`) | — |
| M5: Satellite renderer degradations | yes | one role branch per renderer at the anchors in §6; degradation messages fixed in §7 | — |
| M6: Bundled UI renderer | **no** | lazy `import('mermaid')` lifecycle inside Svelte 5 runes, host-theme → mermaid theme mapping, DOMPurify SVG profile and the jsdom mock strategy need the thinking model; the `A2UINode` branch + test rows ARE mechanical once the component exists | — |
| M7: Docs + conformance + goldens + FEAT-755 handoff notes | yes | sections and anchors listed in §6/§7 | — |

### Module 1: Mermaid source utilities + error codes
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid_source.py` (new);
  `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py` (modify, 4 constants);
  `packages/ai-parrot/src/parrot/outputs/a2ui/graph/__init__.py` (modify, re-exports)
- **Responsibility**: the pure text layer every other module calls — type detection,
  directive normalization, safety check, opt-in `GraphSpec` conversion, phrase-bank
  constants. No I/O, no Pydantic models of its own, no `catalog/__init__` import (it is
  imported BY `catalog/__init__`'s validation pass — importing back would be a cycle).
- **Depends on**: `graph/mermaid.py` (`from_mermaid`, `MermaidCodecError`), `catalog/base.py` (codes)
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid_source.py  (new)
  from parrot.outputs.a2ui.catalog.base import (  # verified: catalog/base.py:61-96 (existing codes); new codes added at :96
      MERMAID_DIAGRAM_TYPE_MISMATCH, MERMAID_SOURCE_TOO_LARGE, MERMAID_UNSAFE_DIRECTIVE, MERMAID_UNSAFE_INTERACTION,
  )
  from parrot.outputs.a2ui.graph.mermaid import MermaidCodecError, from_mermaid  # verified: graph/mermaid.py:126,323
  from parrot.outputs.a2ui.graph.models import GraphSpec  # verified: graph/models.py:179

  MERMAID_DIAGRAM_TYPES: Final[tuple[str, ...]]
  MERMAID_SOURCE_MAX_BYTES: Final[int] = 32_768
  MERMAID_THEMES: Final[tuple[str, ...]] = ("default", "neutral", "dark", "forest", "base")
  MERMAID_DIAGRAM_ROUTE_KEY: Final[str] = "a2ui:MermaidDiagram"
  MERMAID_DIAGRAM_ROUTE_UTTERANCES: Final[tuple[str, ...]] = (
      "as a diagram", "draw this as a diagram", "sequence diagram of", "show the flow as a sequence diagram",
      "class diagram of", "ER diagram of the data model", "gantt chart of the plan", "draw a mindmap",
      "diagrama de secuencia de", "muéstralo como diagrama", "diagrama de clases de", "diagrama entidad-relación",
      "haz un diagrama de flujo", "dibuja un mapa mental",
  )

  class MermaidSourceIssue(TypedDict):
      """One validation finding: ``code`` (a ``catalog.base`` constant), ``message``, ``line_no`` (1-based or None)."""

  def iter_statements(source: str) -> Iterator[tuple[int, str]]:
      """Yield ``(line_no, stripped_line)`` for every statement line.

      Skips blank lines, ``%%`` comments, ``%%{ … }%%`` directive lines and a leading
      YAML front-matter block (``---`` … ``---`` at the very top, which Mermaid allows
      for ``title:``/``config:``). Never raises.
      """

  def detect_diagram_type(source: str) -> str:
      """Return the diagram type of ``source`` from the first token of its first statement.

      Matching is exact and case-sensitive on the header keyword (``_HEADER_TO_TYPE``);
      anything else — including an empty source — is ``"unknown"``. Pure; never raises.
      """

  def normalize_mermaid_source(source: str) -> tuple[str, str | None]:
      """Strip every ``%%{ … }%%`` directive (single- or multi-line) and lift its ``theme``.

      Returns ``(normalized_source, theme)``; ``theme`` is the directive's ``theme`` value
      when it is one of ``MERMAID_THEMES`` (else ``None``). Line endings are normalized to
      ``\\n`` and a single trailing newline is guaranteed. Everything else is preserved
      byte-for-byte. Never raises.
      """

  def check_mermaid_source(source: str, *, declared_type: str | None = None) -> list[MermaidSourceIssue]:
      """Validate ``source`` for the wire; return EVERY issue found (empty list == valid).

      Checks, in order: empty or ``> MERMAID_SOURCE_MAX_BYTES`` UTF-8 bytes
      (``MERMAID_SOURCE_TOO_LARGE``); any line whose stripped form starts with ``%%{``
      (``MERMAID_UNSAFE_DIRECTIVE`` — directives are a builder-side normalization, never
      a wire feature); any statement whose first token is ``click``/``link``/``callback``,
      or that contains ``javascript:`` or ``<script`` case-insensitively
      (``MERMAID_UNSAFE_INTERACTION``); ``declared_type`` set and different from
      ``detect_diagram_type(source)`` (``MERMAID_DIAGRAM_TYPE_MISMATCH``). Pure; never raises.
      """

  def graph_spec_from_mermaid_source(source: str) -> GraphSpec:
      """Opt-in bridge to the typed ``Graph`` vocabulary.

      Normalizes ``source`` and delegates to :func:`from_mermaid`. Succeeds only for the
      codec's flowchart / stateDiagram-v2 / sequenceDiagram subset; raises
      :class:`MermaidCodecError` (naming the offending line) otherwise. Never called
      automatically by any producer or renderer.
      """
  ```
  ```python
  # packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py  (modifies catalog/base.py:96 — append after TRANSFORM_REF_UNKNOWN)
  MERMAID_SOURCE_TOO_LARGE = "MERMAID_SOURCE_TOO_LARGE"
  MERMAID_UNSAFE_DIRECTIVE = "MERMAID_UNSAFE_DIRECTIVE"
  MERMAID_UNSAFE_INTERACTION = "MERMAID_UNSAFE_INTERACTION"
  MERMAID_DIAGRAM_TYPE_MISMATCH = "MERMAID_DIAGRAM_TYPE_MISMATCH"
  ```
  ```python
  # packages/ai-parrot/src/parrot/outputs/a2ui/graph/__init__.py  (modifies graph/__init__.py:12,30 — import + __all__)
  from .mermaid_source import (  # new
      MERMAID_DIAGRAM_ROUTE_KEY, MERMAID_DIAGRAM_ROUTE_UTTERANCES, MERMAID_DIAGRAM_TYPES, MERMAID_SOURCE_MAX_BYTES,
      check_mermaid_source, detect_diagram_type, graph_spec_from_mermaid_source, normalize_mermaid_source,
  )
  ```

### Module 2: `MermaidDiagram` catalog component + validation pass
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/mermaiddiagram.py` (new);
  `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/__init__.py` (modify);
  `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py` (modify)
- **Responsibility**: the registered component (schema, LLM instructions, lowering) and
  the envelope-level safety gate that makes G2 true for every producer, LLM or tool.
- **Depends on**: Module 1; `catalog.register_component`, `BasicNode`, `Component`
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/mermaiddiagram.py  (new)
  from parrot.outputs.a2ui.catalog import register_component  # verified: catalog/__init__.py:114
  from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree  # verified: catalog/base.py:111,170
  from parrot.outputs.a2ui.graph.mermaid_source import MERMAID_DIAGRAM_TYPES, MERMAID_SOURCE_MAX_BYTES, MERMAID_THEMES, detect_diagram_type
  from parrot.outputs.a2ui.models import Component  # verified: models.py:400

  MERMAIDDIAGRAM_SCHEMA: dict[str, Any]   # §2 "Wire schema", verbatim
  MERMAIDDIAGRAM_INSTRUCTIONS: str        # §7 "LLM instructions", verbatim

  @register_component("MermaidDiagram", allowed_parents=["root", "Column"])  # requires_actions/tool_only default False
  class MermaidDiagramComponent:
      """The ``MermaidDiagram`` Parrot-catalog component: opaque, display-only Mermaid source."""

      SCHEMA = MERMAIDDIAGRAM_SCHEMA
      INSTRUCTIONS = MERMAIDDIAGRAM_INSTRUCTIONS

      def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:
          """Lower to ``Card{Column[description, title?, caption?, source]}`` (§2 "Lowered tree").

          The source Text carries ``parrot_role: "mermaid-source"`` plus
          ``parrot_diagram_type`` (the wire ``diagramType`` or, when absent,
          ``detect_diagram_type(source)``) and ``parrot_mermaid_theme`` when ``theme`` is set.
          Deterministic: identical input → byte-identical tree (golden-tested). Never
          validates — ``validate_envelope`` already did.
          """
  ```
  ```python
  # packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py  (modifies catalog/__init__.py:48 import block and :964 call site)
  from parrot.outputs.a2ui.graph.mermaid_source import check_mermaid_source  # module-level import is cycle-free: mermaid_source imports only catalog.base + graph.*

  def _validate_mermaid_sources(envelope: CreateSurface | UpdateComponents, issues: list[dict[str, Any]]) -> None:
      """Append one issue per :func:`check_mermaid_source` finding for every ``MermaidDiagram`` component.

      Runs for EVERY origin (the gate is about renderer safety, not authorship). Each
      issue is ``{"code", "message", "path": <component id>}`` so the aggregate
      ``CatalogValidationError`` shape is unchanged. A missing/non-string ``source`` is
      reported as ``MERMAID_SOURCE_TOO_LARGE`` with an "empty source" message.
      """
  # call site: immediately after `_validate_linked_sources(envelope, origin=origin, issues=issues)` (catalog/__init__.py:964)
  ```
  ```python
  # packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/__init__.py  (modifies :17 — add `mermaiddiagram,  # noqa: F401` after `map,` keeping alphabetical order)
  ```

### Module 3: Builder + exports
- **Path**: `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py` (modify)
- **Responsibility**: the one deterministic Python entry point every tool/adapter uses;
  normalizes BEFORE building so a directive never reaches validation from this lane.
- **Depends on**: Modules 1–2; `build_surface` (`builders.py:79`)
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # packages/ai-parrot/src/parrot/outputs/a2ui/builders.py  (modifies builders.py:62 __all__ and inserts before `def build_graph(` at :330)
  from parrot.outputs.a2ui.graph.mermaid_source import detect_diagram_type, normalize_mermaid_source  # new import next to the graph imports at builders.py:43-54

  def build_mermaid_diagram(
      *,
      source: str,
      title: str | None = None,
      caption: str | None = None,
      theme: str | None = None,
      accessible_description: str | None = None,
      diagram_type: str | None = None,
      surface_id: str = "mermaid-diagram",
      origin: ProducerOrigin = ProducerOrigin.TOOL,  # verified: ProducerOrigin catalog/base.py:99
      metadata: ComponentMetadata | None = None,     # verified: models.py:364
  ) -> CreateSurface:                                 # verified: models.py:446
      """Build a validated single-component ``MermaidDiagram`` ``CreateSurface``.

      Steps: ``normalize_mermaid_source`` (an explicit ``theme`` argument wins over a
      lifted one) → ``diagram_type or detect_diagram_type(...)`` → props
      ``{"source", "diagramType", "title"?, "caption"?, "theme"?, "accessibleDescription"?}``
      → :func:`build_surface` with ``origin`` (default TOOL, like ``build_graph``; pass
      ``ProducerOrigin.LLM`` to apply the LLM gates). Pure: same input → byte-identical envelope.

      Raises:
          CatalogValidationError: from ``validate_envelope`` (size cap, unsafe statement,
              declared ``diagram_type`` mismatch). Never pre-checks — one validation path.
      """
  ```

### Module 4: Tool-facing entry + bot lift
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/mermaid_diagram.py` (new);
  `packages/ai-parrot-tools/src/parrot_tools/__init__.py` (modify, mapping);
  `packages/ai-parrot/src/parrot/bots/base.py` (modify, one membership test)
- **Responsibility**: let any agent/toolkit emit a diagram deterministically from text it
  already has (a documented process, a schema it inspected) and have the bot surface it
  as `response.a2ui_envelope` without touching the formatter.
- **Depends on**: Module 3
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # packages/ai-parrot-tools/src/parrot_tools/mermaid_diagram.py  (new)
  from parrot.outputs.a2ui.builders import build_mermaid_diagram
  from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema  # verified: parrot/tools/abstract.py:282,238
  from pydantic import Field

  class MermaidDiagramArgs(AbstractToolArgsSchema):
      """Arguments for rendering a Mermaid diagram as an inline A2UI surface."""
      source: str = Field(description="Mermaid source (flowchart, sequenceDiagram, classDiagram, erDiagram, gantt, pie, mindmap, …). No %%{init}%% directives, no click statements.")
      title: str | None = Field(default=None, description="Optional title shown above the diagram.")
      caption: str | None = Field(default=None, description="Optional caption shown below the diagram.")
      theme: str | None = Field(default=None, description="Optional Mermaid theme hint: default, neutral, dark, forest, base.")
      accessible_description: str | None = Field(default=None, description="One-sentence screen-reader summary of what the diagram shows.")

  class MermaidDiagramTool(AbstractTool):
      """Render Mermaid source as an inline A2UI ``MermaidDiagram`` surface.

      Use it when the answer is best shown as a diagram (sequence, class, ER, state,
      flowchart, gantt, pie, mindmap, gitGraph, C4, …). The source is validated
      (size cap, no init directives, no click/javascript statements) and returned as an
      A2UI envelope the chat UI renders inline; text-only channels show the source.
      """
      name = "render_mermaid_diagram"
      description = "Render Mermaid diagram source (sequence, class, ER, state, flowchart, gantt, pie, mindmap, C4, …) as an inline A2UI diagram surface; pass source and optionally title, caption, theme, accessible_description."
      args_schema = MermaidDiagramArgs

      async def _execute(  # verified: AbstractTool._execute hook parrot/tools/abstract.py:604
          self, *, source: str, title: str | None = None, caption: str | None = None, theme: str | None = None,
          accessible_description: str | None = None, **kwargs: Any,
      ) -> dict[str, Any]:
          """Return ``{"a2ui_envelope": <bare CreateSurface dump>, "artifacts": [{"type": "a2ui_surface", ...}], "diagram_type", "source"}`` (§2).

          Raises ``CatalogValidationError`` unchanged on invalid source — the framework's
          ``execute()`` wraps it into a failed ``ToolResult`` (abstract.py:916) and the
          LLM sees the issue codes/messages.
          """
  ```
  ```python
  # packages/ai-parrot-tools/src/parrot_tools/__init__.py  (modifies :127 — add after the publish_surface line)
  "mermaid_diagram": "parrot_tools.mermaid_diagram.MermaidDiagramTool",
  ```
  ```python
  # packages/ai-parrot/src/parrot/bots/base.py  (modifies :1042 inside _extract_last_linked_surface_result)
  _LIFTABLE_SURFACE_ARTIFACT_TYPES = frozenset({"a2ui_linked_surface", "a2ui_surface"})  # module-level constant
  # `a.get("type") == "a2ui_linked_surface"`  →  `a.get("type") in _LIFTABLE_SURFACE_ARTIFACT_TYPES`
  # Docstring (:1029) gains: "and the FEAT-753 `render_mermaid_diagram` tool (`type: "a2ui_surface"`)".
  ```

### Module 5: Satellite renderer degradations
- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py`,
  `.../adaptive_cards.py`, `.../interactive_html.py` (modify); `pdf.py` inherits
- **Responsibility**: G3 — the lowered `mermaid-source` Text renders as a monospace,
  copyable block with ONE recorded degradation per diagram; capabilities are **not**
  changed (`MermaidDiagram` is never in `supported_components` — it always lowers,
  exactly like every Parrot composite these renderers do not intercept).
- **Depends on**: Module 2 (role name)
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py  (modifies ssr_html.py:532 — new branch BEFORE `if role == "html_document":`)
  # in SSRHTMLRenderer._render_Text (verified: ssr_html.py:516):
  #   if role == "mermaid-source":
  #       degradations.append(degradation_record(node, "ssr-html has no Mermaid engine; source shown as a code block"))  # verified: degrade.py:46
  #       return '<pre class="a2ui-mermaid-source"><code class="language-mermaid" data-diagram-type="…">{escaped}</code></pre>'

  # packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py  (modifies adaptive_cards.py:466 — new branch BEFORE `if role == "html_document":`)
  #   if role == "mermaid-source":
  #       state.degradations.append(degradation_record(node, "adaptive_cards has no Mermaid engine; source shown as monospace text"))
  #       return TextBlock(text=<source>, fontType="Monospace", wrap=True)

  # packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py  (modifies interactive_html.py:1117 `_render_prim_Text`)
  #   if role == "mermaid-source":
  #       degradations.append(degradation_record(node, "interactive-html does not bundle mermaid.js (self-contained invariant); source shown as a code block"))
  #       return '<pre class="a2ui-mermaid-source"><code class="language-mermaid">{escaped}</code></pre>'
  #   `_INTERCEPTED` (:136) and `supported_components` (:875-899) are NOT touched.
  ```

### Module 6: Bundled UI renderer (`ai-parrot-server/ui`)
- **Path**: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIMermaidDiagram.svelte` (new),
  `.../A2UIMermaidDiagram.test.ts` (new), `.../A2UINode.svelte` (modify), `.../A2UINode.test.ts` (modify),
  `packages/ai-parrot-server/ui/package.json` (modify)
- **Responsibility**: G7 — native inline rendering in the reference SPA, behind the
  existing `features.a2ui` flag (`ui/src/lib/features.ts:31`; no new flag).
- **Depends on**: Module 2 (wire shape); npm `mermaid` (lazy-imported), `dompurify` (already a dependency, `package.json:38`)
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```ts
  // packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIMermaidDiagram.svelte  (new)
  <script module lang="ts">
    /** The MermaidDiagram component's own (already-resolved) top-level props. Mirrors MERMAIDDIAGRAM_SCHEMA. */
    export interface MermaidDiagramProperties {
      source: string; diagramType?: string; title?: string; caption?: string;
      theme?: 'default' | 'neutral' | 'dark' | 'forest' | 'base'; accessibleDescription?: string;
    }
    /** Pure: pick the mermaid theme — the wire `theme` hint wins, else 'dark' when the host is dark, else 'default'. Unit-tested without rendering. */
    export function resolveMermaidTheme(hint: string | undefined, hostIsDark: boolean): 'default' | 'neutral' | 'dark' | 'forest' | 'base';
  </script>
  <script lang="ts">
    // let { properties }: { properties: MermaidDiagramProperties } = $props();
    // $effect: const mermaid = (await import('mermaid')).default;  — lazy, once per module (same idiom as ECharts.svelte:110)
    //   mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme });
    //   await mermaid.parse(source)  → on error: status = 'error' (code-block fallback + short notice, never throws)
    //   const { svg } = await mermaid.render(`a2ui-mermaid-${uid}`, source);
    //   svgHtml = DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true, svgFilters: true } });   // then {@html svgHtml}
    // Markup: optional <h3> title · <figure role="img" aria-label={accessibleDescription}> · optional <figcaption>
    //   · <details><summary>Mermaid source</summary><pre><code>{source}</code></pre></details> (always present — copyable)
  </script>
  ```
  ```svelte
  <!-- packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UINode.svelte  (modifies :250 — new branch BEFORE `{:else if component === 'HtmlDocument'}`) -->
  {:else if component === 'MermaidDiagram'}
    <A2UIMermaidDiagram properties={resolved as unknown as MermaidDiagramProperties} />
  ```
  ```json
  // packages/ai-parrot-server/ui/package.json  (modifies :46 — add after "marked")
  "mermaid": "^11.x"   // pin the current 11.x at task time (see §7 External Dependencies)
  ```

### Module 7: Docs + conformance + goldens + FEAT-755 handoff notes
- **Path**: `docs/outputs/a2ui-v1.md`, `docs/frontend/agentdashboard-a2ui-reference.md` (modify);
  `packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py` (modify);
  `packages/ai-parrot/tests/outputs/a2ui/golden/mermaiddiagram_lowered.json` (new); new test files listed in §4
- **Responsibility**: the wire contract for every consumer (navigator-frontend-next
  included), the cross-cutting acceptance tests, and the exact handoff FEAT-755 needs
  (schema location, instructions, utterance constant, lift artifact type).
- **Depends on**: Modules 1–6
- **Interface Skeleton** *(docs/tests — contents listed in §4 and §7; no code interfaces)*:
  ```text
  docs/outputs/a2ui-v1.md
    · catalog table row (:78): add `MermaidDiagram` to the Parrot list
    · new `## MermaidDiagram — opaque Mermaid source (FEAT-753)` inserted BEFORE `## Adaptive Cards and the Teams submit flow` (:474):
      wire shape · validation codes · lowered fallback table · renderer matrix · relationship with Graph · LLM/tool lanes
    · `metadata.extensions` table: `parrot_role` gains "mermaid-source"; new keys `parrot_diagram_type`, `parrot_mermaid_theme`
  docs/frontend/agentdashboard-a2ui-reference.md
    · §5.2 heading (:497) and the §5.4 "still 10 composites" sentence (:616): 10 → 11 composites
    · §5.3 renderer table (:582): interactive-html row notes MermaidDiagram = lowered code block (+degraded)
    · new `### 5.5 MermaidDiagram (FEAT-753)` inserted BEFORE `## 6. Dashboards, infographics and widgets` (:710):
      frontend contract (lazy mermaid.js, securityLevel strict, DOMPurify, fallback), example envelope
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_detect_diagram_type_table` (parametrized over every `_HEADER_TO_TYPE` key, `graph TD`, front-matter + comments before the header, empty → `unknown`) | M1 | detection is exact, skips front-matter/comments/directives |
| `test_normalize_strips_directives_and_lifts_theme` | M1 | single-line and multi-line `%%{init: {"theme": "dark"}}%%` removed; theme returned; non-theme directives removed with `None`; byte-identical remainder |
| `test_check_rejects_oversize_and_empty` | M1 | `MERMAID_SOURCE_TOO_LARGE` for `""` and for `MERMAID_SOURCE_MAX_BYTES + 1` bytes (multi-byte chars counted as bytes) |
| `test_check_rejects_surviving_directive` | M1 | `MERMAID_UNSAFE_DIRECTIVE` with `line_no` |
| `test_check_rejects_click_link_callback_javascript_script` (parametrized) | M1 | each vector → `MERMAID_UNSAFE_INTERACTION`; `clickable` as a node label is NOT rejected (first-token match) |
| `test_check_reports_all_issues_not_first` | M1 | a source with 3 problems yields 3 issues |
| `test_check_type_mismatch` | M1 | `declared_type="sequence"` on a flowchart → `MERMAID_DIAGRAM_TYPE_MISMATCH`; `declared_type=None` never raises it |
| `test_graph_spec_from_mermaid_source_subset_and_rejection` | M1 | flowchart/state/sequence samples → `GraphSpec`; `classDiagram` → `MermaidCodecError` |
| `test_registration_flags` | M2 | `get_component("MermaidDiagram")`: `tool_only is False`, `requires_actions is False`, `allowed_parents == ["root", "Column"]`, `catalog_id == DEFAULT_CATALOG_ID` |
| `test_schema_shape` | M2 | `required == ["source"]`; `diagramType.enum == list(MERMAID_DIAGRAM_TYPES)`; `source.maxLength == MERMAID_SOURCE_MAX_BYTES` |
| `test_lowering_golden` | M2 | byte-identical to `golden/mermaiddiagram_lowered.json` across two runs (pattern: `test_components_htmldocument.py:41-45`) |
| `test_lowering_roles_and_extensions` | M2 | order description/title/caption/source; `parrot_role == "mermaid-source"`; `parrot_diagram_type`; `parrot_mermaid_theme` only when set; Card `parrot_variant == "mermaid-diagram"` |
| `test_lowering_emits_only_basic_primitives` | M2 | every node is a registered `is_primitive` component (pattern: `test_components_graph.py:76`) |
| `test_validate_envelope_llm_origin_accepts_clean_source` | M2 | `origin=LLM` passes (NOT tool-only — the inverse of `test_components_htmldocument.py:81`) |
| `test_validate_envelope_rejects_unsafe_for_both_origins` (parametrized over TOOL/LLM × 4 codes) | M2 | issues carry `path == component id`; aggregate error lists all |
| `test_build_mermaid_diagram_normalizes_and_detects` | M3 | directive stripped from the wire `source`; `theme` lifted; `diagramType` filled; `origin` default TOOL; explicit `theme=` wins |
| `test_build_mermaid_diagram_rejects_declared_mismatch` | M3 | `diagram_type="er"` on a sequence → `CatalogValidationError` |
| `test_build_mermaid_diagram_in_all` | M3 | `"build_mermaid_diagram" in builders.__all__` (pattern: `test_builders_graph.py:53`) |
| `test_tool_schema_and_docstring` / `test_tool_execute_returns_lift_shape` / `test_tool_propagates_validation_error` | M4 | mirrors `test_publish_surface_tool.py:21-35`; result has bare `a2ui_envelope` (no `version`), `artifacts[0].type == "a2ui_surface"` |
| `test_tool_registered_in_mapping` | M4 | `parrot_tools` mapping resolves `"mermaid_diagram"` to the class |
| `test_extract_last_linked_surface_result_accepts_a2ui_surface` | M4 | lift returns the wrapped envelope for `type: "a2ui_surface"`; `{"type": "chart"}` still ignored (`test_linked_surface_lifting.py:39-53` unchanged) |
| `test_ssr_html_mermaid_source_code_block_and_degraded` | M5 | `<pre class="a2ui-mermaid-source"><code class="language-mermaid"` present, source HTML-escaped (`<script` sample never appears unescaped), ONE degraded record naming "Mermaid" |
| `test_pdf_inherits_mermaid_degradation` | M5 | `pytest.importorskip("weasyprint")`; same record |
| `test_adaptive_cards_mermaid_monospace_textblock` | M5 | `fontType == "Monospace"`, `wrap is True`, degraded record |
| `test_interactive_html_mermaid_not_intercepted_code_block` | M5 | `"MermaidDiagram" not in _INTERCEPTED`; output contains the code block; no `<script src` added; degraded record |
| `A2UINode dispatches MermaidDiagram` (vitest) | M6 | `vi.mock('mermaid')` — the stub's `render` resolves `{svg: '<svg data-testid="mermaid-svg"/>'}`; the SVG and the `<details>` source appear |
| `A2UIMermaidDiagram falls back on parse error` (vitest) | M6 | stub `parse` rejects → `<pre><code>` fallback + notice; no throw |
| `resolveMermaidTheme` (vitest) | M6 | hint wins; dark host → `dark`; default otherwise |
| `A2UINode leaves unknown components on the placeholder` (vitest, existing row `A2UINode.test.ts:239` kept green) | M6 | regression |

### Integration Tests
| Test | Description |
|---|---|
| `TestBuildersConformance.test_build_mermaid_diagram` (`test_all_emitters.py`) | `_assert_conformant(build_mermaid_diagram(...))` for TOOL **and** LLM origins — catalog allowlist + lowered Basic wire schema (`:116-131`) |
| `TestGraphToMermaidDiagramRoundtrip` (`test_all_emitters.py`) | for the flow fixture (`:466-500`) and the three codec dialects: `build_mermaid_diagram(source=to_mermaid(spec))` validates, `diagramType ∈ {flowchart, state, sequence}`, `graph_spec_from_mermaid_source(...) == spec` modulo `accessible_description`/`size` (`test_mermaid.py:23-29` helper semantics) |
| `TestCatalogDefinitionIncludesMermaidDiagram` (`test_all_emitters.py`) | `export_catalog_definition()["components"]` contains `MermaidDiagram`; viz-core export does not |
| `TestMermaidDiagramRendersOnEveryRegisteredRenderer` (`test_all_emitters.py`) | every registered renderer's `render()` returns an artifact, never raises; non-UI lanes record exactly one `degraded` entry for the diagram |
| `test_ask_lifts_mermaid_tool_result` (`tests/bots/test_linked_surface_lifting.py`) | source-level/`_base_bot()` style: a `render_mermaid_diagram` tool call result is lifted with the same precedence as the linked lift |

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
  - packages/ai-parrot/tests/outputs/a2ui/test_catalog.py
  - packages/ai-parrot/tests/outputs/a2ui/test_catalog_parity.py
  - packages/ai-parrot/tests/outputs/a2ui/test_components_htmldocument.py
  - packages/ai-parrot/tests/outputs/a2ui/test_components_graph.py
  - packages/ai-parrot/tests/outputs/a2ui/test_builders.py
  - packages/ai-parrot/tests/outputs/a2ui/test_builders_graph.py
  - packages/ai-parrot/tests/outputs/a2ui/test_lazy_imports.py
  - packages/ai-parrot/tests/outputs/a2ui/test_no_exec.py
  - packages/ai-parrot/tests/outputs/a2ui/graph/test_mermaid.py
  - packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py
  - packages/ai-parrot/tests/bots/test_linked_surface_lifting.py
  - packages/ai-parrot-tools/tests/test_publish_surface_tool.py
  - packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_ssr_html.py
  - packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_interactive_html.py
  - packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_adaptive_cards.py
  - packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_pdf.py
  markers: none
- kind: vitest
  cwd: packages/ai-parrot-server/ui
  tests:
  - src/lib/components/agents/canvas/a2ui/A2UINode.test.ts
  - src/lib/components/agents/canvas/a2ui/a2ui-kind.test.ts

> The new test files this feature CREATES (`graph/test_mermaid_source.py`,
> `test_components_mermaiddiagram.py`, `test_builders_mermaid.py`,
> `packages/ai-parrot-tools/tests/test_mermaid_diagram_tool.py`,
> `A2UIMermaidDiagram.test.ts`) are added to this list by `/sdd-task` once they exist;
> `test_lazy_imports.py` guards that `parrot.bots.data` (a probed entry point, `:8`) never
> ends up importing `catalog.parrot` through the FEAT-755 phrase-bank constant — that is
> why the constant lives in `graph/mermaid_source.py`, not in the component module.

### Test Data / Fixtures
```python
# packages/ai-parrot/tests/outputs/a2ui/graph/test_mermaid_source.py (new) — shared samples, reused by the component/builder tests
SEQUENCE_SRC = "sequenceDiagram\n    participant A as Alice\n    A->>B: hello\n"
CLASS_SRC = "classDiagram\n    class Animal {\n      +String name\n    }\n    Animal <|-- Dog\n"
ER_SRC = "erDiagram\n    CUSTOMER ||--o{ ORDER : places\n"
FRONTMATTER_SRC = "---\ntitle: Checkout\n---\n%% a comment\nflowchart LR\n    a --> b\n"
DIRECTIVE_SRC = '%%{init: {"theme": "dark", "flowchart": {"htmlLabels": true}}}%%\nflowchart TD\n    a --> b\n'
CLICK_SRC = "flowchart TD\n    a --> b\n    click a href \"javascript:alert(1)\"\n"
OVERSIZE_SRC = "flowchart TD\n" + "\n".join(f"n{i} --> n{i+1}" for i in range(6000))   # > 32 KiB

# packages/ai-parrot/tests/outputs/a2ui/test_components_mermaiddiagram.py — golden component (mirrors test_components_htmldocument.py:25-31)
def _mermaid_component() -> Component:
    return Component(id="blk-000", component="MermaidDiagram", source=SEQUENCE_SRC, diagramType="sequence",
                     title="Login flow", caption="Happy path", theme="neutral", accessibleDescription="Alice greets Bob")

# packages/ai-parrot/tests/outputs/a2ui/golden/mermaiddiagram_lowered.json — produced ONCE by `_dump(lower(...))`, then frozen.

# vitest: A2UIMermaidDiagram.test.ts
vi.mock('mermaid', () => ({ default: { initialize: vi.fn(), parse: vi.fn().mockResolvedValue(true),
                                       render: vi.fn().mockResolvedValue({ svg: '<svg data-testid="mermaid-svg"></svg>' }) } }));
vi.mock('$lib/features', () => ({ features: { a2ui: true, charts: true, maps: false } }));   // pattern: A2UINode.test.ts:20
```

### E2E Scenarios

> Optional (FEAT-581) — omitted: this feature has no deterministic E2E surface
> (no fixture target renders mermaid.js; the bundled UI is covered by vitest with a
> mocked `mermaid`, the server lanes by pytest). The frontmatter carries no `e2e` key.

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] **AC-1** `get_component("MermaidDiagram")` resolves under `DEFAULT_CATALOG_ID` with `tool_only=False`, `requires_actions=False`, `allowed_parents=["root","Column"]`; `export_catalog_definition()` lists it; the viz-core export does not.
- [ ] **AC-2** `validate_envelope` rejects — for BOTH origins — an empty/oversize source, any surviving `%%{` directive, any `click`/`link`/`callback`/`javascript:`/`<script` vector and a declared `diagramType` mismatch, reporting every issue with the component id as `path`; a clean LLM-origin envelope passes.
- [ ] **AC-3** `build_mermaid_diagram(source=DIRECTIVE_SRC)` emits a wire `source` with no directive, `theme="dark"`, `diagramType="flowchart"`; identical inputs give byte-identical envelopes.
- [ ] **AC-4** Lowering is golden-stable, Basic-only, and never drops the source; the lowered envelope validates against the vendored `agent_to_renderer.json` (`_assert_conformant`).
- [ ] **AC-5** For every `GraphSpec` fixture in the conformance suite: `to_mermaid(spec)` is a valid `MermaidDiagram.source`, detects as `flowchart`/`state`/`sequence`, and `graph_spec_from_mermaid_source` round-trips it modulo `accessible_description`/`size`. `from_mermaid`/`to_mermaid` are byte-unchanged.
- [ ] **AC-6** `render_mermaid_diagram` is resolvable from the `parrot_tools` mapping, returns the §2 result shape, and `AbstractBot.ask()` lifts it into `response.a2ui_envelope` (wrapped `{"version": "v1.0", "createSurface": …}`) with the existing precedence (interactive > infographic > dict lift); every existing lift test stays green.
- [ ] **AC-7** `ssr_html`, `pdf`, `adaptive_cards`, `interactive-html` render a `MermaidDiagram` envelope without raising, show the source as a monospace block (HTML-escaped where applicable), record exactly ONE `degraded` entry per diagram, and never add a `<script src=…>`; `echarts`/`folium_map` behave as for any other non-focal Parrot composite (no new code).
- [ ] **AC-8** The bundled UI renders `MermaidDiagram` inline via a lazy-imported mermaid.js with `securityLevel: "strict"`, `startOnLoad: false`, DOMPurify-sanitized SVG, an always-present collapsible source block, and a code-block fallback on parse/render failure; `pnpm build` ships mermaid in its own async chunk (verified with `ls dist/assets | grep -i mermaid`), and `pnpm test` passes with `mermaid` mocked.
- [ ] **AC-9** `MERMAID_DIAGRAM_ROUTE_KEY`/`MERMAID_DIAGRAM_ROUTE_UTTERANCES` are importable from `parrot.outputs.a2ui.graph` without importing `catalog.parrot` (`test_lazy_imports.py` green); `MERMAIDDIAGRAM_INSTRUCTIONS` appears in `catalog_instructions()`.
- [ ] **AC-10** `docs/outputs/a2ui-v1.md` and `docs/frontend/agentdashboard-a2ui-reference.md` document the component (wire shape, codes, lowering, renderer matrix, frontend contract, Graph relationship) and the composite count reads 11.
- [ ] **AC-11** No breaking change: every pre-existing test in the Validation Contract passes unmodified except the two rows this spec extends (`A2UINode.test.ts`, `test_linked_surface_lifting.py`), which only GAIN cases.
- [ ] **AC-12** `ruff check` (TID251 import bans) and `black --check` clean on every touched Python file; no `exec(`/`eval(` (`test_no_exec.py`).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports
<!-- Exact import statements confirmed to work. Agents MUST use these verbatim. -->
```python
from parrot.outputs.a2ui.catalog import register_component, get_component, list_components, validate_envelope, validate_message, catalog_instructions, DEFAULT_CATALOG_ID, ProducerOrigin  # verified: catalog/__init__.py:71-93 (__all__), :114, :209, :253, :743, :458, :314
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree, CatalogValidationError, ComponentDefinition, ProducerOrigin, DEFAULT_CATALOG_ID, TOOL_ONLY_NOT_ALLOWED_FOR_LLM, TRANSFORM_REF_UNKNOWN  # verified: catalog/base.py:111, :170, :317, :234, :99, :53, :86, :96
from parrot.outputs.a2ui.catalog.base import to_components  # verified: catalog/base.py:174
from parrot.outputs.a2ui.catalog.parrot import htmldocument  # verified: catalog/parrot/__init__.py:17
from parrot.outputs.a2ui.catalog.parrot.htmldocument import HtmlDocumentComponent, HTMLDOCUMENT_SCHEMA, parse_html_document_placeholder_title  # verified: htmldocument.py:61, :24, :105
from parrot.outputs.a2ui.catalog.viz_core import VIZ_CORE_CATALOG_ID  # verified: catalog/viz_core/__init__.py:28
from parrot.outputs.a2ui.catalog.viz_core.graph import GraphComponent, GRAPH_SCHEMA  # verified: catalog/viz_core/graph.py:64, :35
from parrot.outputs.a2ui.catalog.export import export_catalog_definition  # verified: catalog/export.py:215
from parrot.outputs.a2ui.graph import GraphSpec, to_mermaid, from_mermaid, MermaidCodecError  # verified: graph/__init__.py:11-28
from parrot.outputs.a2ui.graph.mermaid import MermaidCodecError, from_mermaid, to_mermaid  # verified: graph/mermaid.py:67 (__all__), :126, :323, :206
from parrot.outputs.a2ui.graph.models import GraphSpec, GraphKind, VizSize  # verified: graph/models.py:179, :47, :54
from parrot.outputs.a2ui.builders import build_surface, build_html_document, build_graph  # verified: builders.py:79, :278, :330
from parrot.outputs.a2ui.models import Component, ComponentMetadata, CreateSurface, A2UIAgentMessage  # verified: models.py:400, :364, :446, :695
from parrot.outputs.a2ui.serialization import serialize  # verified: serialization.py:104
from parrot.outputs.a2ui.renderers.degrade import degradation_record, degrade  # verified: renderers/degrade.py:46, :24
from parrot.outputs.a2ui.renderers import RendererCapabilities  # verified: renderers/__init__.py:51
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema, ToolResult  # verified: parrot/tools/abstract.py:282, :238, :251
from parrot.outputs.a2ui_renderers.ssr_html import SSRHTMLRenderer  # verified: a2ui_renderers/ssr_html.py (class; test_graph_html.py:54)
from parrot.outputs.a2ui_renderers.interactive_html import InteractiveHTMLRenderer  # verified: a2ui_renderers/interactive_html.py:903
from parrot.outputs.a2ui_renderers.adaptive_cards import AdaptiveCardsRenderer  # verified: test_all_emitters.py:447
from parrot.outputs.a2ui_renderers._intercept import intercepts, resolve_component_catalog  # verified: a2ui_renderers/_intercept.py:21
```

### Existing Class Signatures
<!-- Exact signatures of classes/methods that tasks will extend or call.
     Include attribute types and method signatures with line numbers. -->
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py
def register_component(name: str, *, requires_actions: bool = False, catalog_id: str = DEFAULT_CATALOG_ID, is_primitive: bool = False,
                       allowed_parents: list[str] | None = None, allowed_children: list[str] | None = None, tool_only: bool = False) -> Callable[[type], type]:  # line 114
def get_component(name: str, catalog_id: str | None = None) -> RegisteredComponent:  # line 209
def list_components(catalog_id: str | None = None) -> list[ComponentDefinition]:  # line 253
def catalog_instructions(catalog_ids: Sequence[str] | None = None) -> str:  # line 314
def validate_envelope(envelope: CreateSurface | UpdateComponents, *, origin: ProducerOrigin = ProducerOrigin.TOOL, surface_catalog_id: str | None = None) -> None:  # line 743
#   issues: list[dict[str, Any]] with {"code", "message", "path"}  (line 799); tool_only gate at line 880; `_validate_linked_sources(envelope, origin=origin, issues=issues)` at line 964
def _validate_filter_params(...)  # line 521 — precedent for a hard-coded, component-specific validation pass
_STRUCTURED_INLINE_DATA_COMPONENTS = frozenset({"Chart", "DataTable", "Map"})  # line 110

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py
DEFAULT_CATALOG_ID = "https://parrot.dev/catalogs/v1"  # line 53
TOOL_ONLY_NOT_ALLOWED_FOR_LLM = "TOOL_ONLY_NOT_ALLOWED_FOR_LLM"  # line 86
TRANSFORM_REF_UNKNOWN = "TRANSFORM_REF_UNKNOWN"  # line 96  ← new codes appended after this
class ProducerOrigin(str, Enum): TOOL = "tool"; LLM = "llm"  # line 99
class BasicNode(BaseModel):  # line 111 — extra="allow"; id, component, child, children, template_source, tabs, metadata
BasicTree = BasicNode  # line 170
def to_components(tree: BasicNode, *, id_prefix: str = "blk") -> list[Component]:  # line 174
class ComponentDefinition(BaseModel): name, catalog_id, schema_ (alias "schema"), instructions, requires_actions, is_primitive, allowed_parents, allowed_children, tool_only  # line 234
class CatalogValidationError(CatalogError):  # line 317 — .code / .issues

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/htmldocument.py  (the opaque-surface precedent)
HTMLDOCUMENT_SCHEMA: dict[str, Any]  # line 24
@register_component("HtmlDocument", allowed_parents=["root", "Column"], tool_only=True)  # line 60
class HtmlDocumentComponent: SCHEMA; INSTRUCTIONS; def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree  # line 61, 67

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/viz_core/graph.py
GRAPH_SCHEMA = derive_schema(GraphSpec, binding_fields=("data",), required=("nodes", "edges"))  # line 35
class GraphComponent: def lower(...)  # line 64, 76 — lowered source Text uses parrot_role "graph-source" (line 144), Card parrot_variant "graph" (line 152)

# packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py
__all__ = ["MermaidCodecError", "from_mermaid", "to_mermaid"]  # line 67
_UNSUPPORTED_PREFIXES = ("classDef", "click", "style", "linkStyle", "loop", "alt", "par", "note", "Note")  # line 77
class MermaidCodecError(CatalogValidationError): def __init__(self, line_no: int, line: str, reason: str)  # line 126, 139
def _prepare_lines(text: str) -> list[tuple[int, str]]:  # line 174 — raises on "%%{" (line 191)
def to_mermaid(spec: GraphSpec) -> str:  # line 206 — headers: "flowchart <dir>", "stateDiagram-v2", "sequenceDiagram"
def from_mermaid(text: str) -> GraphSpec:  # line 323 — dispatch on header prefix (lines 344-350)

# packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py
GraphKind = Literal["flowchart", "state", "sequence", "dag"]  # line 47
VizSize = Literal["inline", "tile", "hero"]  # line 54
class GraphSpec(BaseModel): kind: GraphKind = "flowchart" (line 216); size: VizSize = "tile" (line 220)  # line 179

# packages/ai-parrot/src/parrot/outputs/a2ui/builders.py
__all__ = [ "build_card", "build_chart", "build_datatable", "build_graph", "build_html_document", ... ]  # line 57-69
def build_surface(component: str, properties: dict[str, Any], *, surface_id: str, component_id: str = "root", data_model: dict[str, Any] | None = None,
                  origin: ProducerOrigin = ProducerOrigin.LLM, metadata: ComponentMetadata | None = None, surface_metadata: SurfaceMetadata | None = None) -> CreateSurface:  # line 79
def build_html_document(*, title: str, html: str | None = None, src_url: str | None = None, theme: str | None = None,
                        surface_id: str = "html-document", metadata: ComponentMetadata | None = None) -> CreateSurface:  # line 278 — XOR in Python, origin=TOOL
def build_graph(*, nodes, edges, kind="flowchart", ..., surface_id: str = "graph", origin: ProducerOrigin = ProducerOrigin.TOOL) -> CreateSurface:  # line 330

# packages/ai-parrot/src/parrot/outputs/a2ui/models.py
class ComponentMetadata(BaseModel): extensions: Extensions | None  # line 364 (extra="forbid")
class Component(BaseModel): id: str; component: str; catalog_id: str | None (alias catalogId); child; children; weight; accessibility; checks; action; metadata  # line 400 (extra="allow" → props in model_extra)
class CreateSurface(A2UIMessageBase): surface_id (alias surfaceId); catalog_id; send_data_model; components: list[Component]; data_model (alias dataModel); metadata  # line 446

# packages/ai-parrot/src/parrot/bots/base.py
def _extract_last_linked_surface_result(self, tool_calls: Optional[List[Any]]) -> Optional[dict]:  # line 1023
#   `isinstance(a, dict) and a.get("type") == "a2ui_linked_surface" for a in artifacts`  # line 1042 — the membership test M4 generalizes
#   returns `_wrap_create_surface(result["a2ui_envelope"])`  # line 1044; lift precedence block at lines 1674-1686

# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractToolArgsSchema(BaseModel): _context_fields: ClassVar[frozenset[str]]  # line 238
class ToolResult(BaseModel): success, status, result, error, metadata, ...  # line 251
class AbstractTool(EventEmitterMixin, ABC): name: str; description: str; args_schema: Type[BaseModel]; return_direct: bool = False  # line 282, 296-299
    async def _execute(self, **kwargs) -> Any:  # line 604 (subclass hook)
    async def execute(self, *args, **kwargs) -> ToolResult:  # line 916

# packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py  (tool precedent)
class PublishSurfaceArgs(AbstractToolArgsSchema)  # line 35
class PublishSurfaceTool(AbstractTool): name = "publish_surface"; description; args_schema = PublishSurfaceArgs; async def _execute(self, *, kind, title, envelope, ..., **kwargs) -> dict[str, Any]  # line 65, 127
# packages/ai-parrot-tools/src/parrot_tools/__init__.py — name → dotted-path mapping, e.g. `"publish_surface": "parrot_tools.ui_surfaces.PublishSurfaceTool",`  # line 127

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py
class SSRHTMLRenderer: def _lower_composites(self, envelope, degradations) -> CreateSurface  # line 295
    def _render_Text(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:  # line 516 — role branches "graph-svg" (524), "html_document" (532)
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py
#   Text role dispatch: `if role == "html_document":`  # line 466 (TextBlock / ActionOpenUrl degradation precedent)
# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py
_INTERCEPTED = {"Chart", "DataTable", "Infographic", "Map", "HtmlDocument"}  # line 136
_GRAPH_INTERCEPT_TABLE = frozenset({(VIZ_CORE_CATALOG_ID, "Graph")})  # line 147
@register_a2ui_renderer(_SURFACE_NAME, RendererCapabilities(..., supported_components={... "Graph"}))  # lines 866-902
class InteractiveHTMLRenderer(AbstractA2UIRenderer):  # line 903
    def _lower_composites(self, envelope: CreateSurface) -> CreateSurface:  # line 981
    def _render_top(self, comp, by_id, degradations) -> str:  # line 1024 — `if name == "HtmlDocument":` at 1034 / nested at 1051
    def _render_prim_Text(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:  # line 1117
    def _render_htmldocument(self, props: dict[str, Any]) -> str:  # line 1649 (sandboxed iframe)
# packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py
class RendererCapabilities(BaseModel): interactive; supports_actions; supports_updates; output; supported_catalog_ids; supported_components: set[str]  # line 51-75
# packages/ai-parrot/src/parrot/outputs/a2ui/renderers/degrade.py
def degrade(node: BasicNode, reason: str) -> BasicNode  # line 24
def degradation_record(node: BasicNode, reason: str) -> dict[str, Any]  # line 46

# packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py
class SurfaceNegotiationService: async def _respond_html(self, record: UISurfaceRecord) -> web.Response  # line 288 — InteractiveHTMLRenderer().render(envelope), body served verbatim
# packages/ai-parrot-server/src/parrot/handlers/csp.py
def build_csp_headers(...)  # line 69 — script-src 'self' 'unsafe-inline' + JSBundle CDN origins (infographic lane only)

# packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UINode.svelte  (Svelte 5 runes)
let { descriptor, dataModel, surfaceCatalogId }: { descriptor: SectionDescriptor; dataModel: Record<string, unknown>; surfaceCatalogId?: string } = $props();  // lines 22-34
let resolved = $derived(resolveProps(properties, dataModel));  // line 38
{:else if component === 'HtmlDocument'}  // line 250 — sandboxed <iframe sandbox="allow-scripts"> branch; generic placeholder at lines 324-328
// packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIGraph.svelte — `<script module>` exports typed props + pure helpers (lines 1-75), imports ECharts wrapper (line 198)
// packages/ai-parrot-server/ui/src/lib/components/visualizations/ECharts.svelte — `fullEchartsPromise ??= import("echarts")` (line 110): the lazy-import idiom to mirror
// packages/ai-parrot-server/ui/src/lib/features.ts — `features.a2ui` (line 31), `features.charts` (line 26)
// packages/ai-parrot-server/ui/package.json — deps include "dompurify": "^3.4.17" (line 38), "marked": "^15.0.4" (line 46); NO "mermaid"
```

### Integration Points
<!-- How new code connects to existing code. Specify exact method calls. -->
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `MermaidDiagramComponent` | `register_component("MermaidDiagram", allowed_parents=["root","Column"])` | decorator | `catalog/__init__.py:114` |
| `catalog/parrot/__init__.py` | `mermaiddiagram` module | import side effect | `catalog/parrot/__init__.py:13-24` |
| `_validate_mermaid_sources` | `validate_envelope` issue list | appended pass after `_validate_linked_sources(...)` | `catalog/__init__.py:964` |
| `check_mermaid_source` | `catalog.base` error codes | import | `catalog/base.py:96` (append point) |
| `graph_spec_from_mermaid_source` | `from_mermaid` | function call | `graph/mermaid.py:323` |
| `build_mermaid_diagram` | `build_surface("MermaidDiagram", props, surface_id=…, origin=…, metadata=…)` | function call | `builders.py:79` |
| `MermaidDiagramTool._execute` | `build_mermaid_diagram(...)` → `.model_dump(by_alias=True, mode="json")` | function call | `builders.py` (new), `test_linked_surface_lifting.py:53` (bare dump contract) |
| `parrot_tools` mapping | `"mermaid_diagram": "parrot_tools.mermaid_diagram.MermaidDiagramTool"` | dict entry | `parrot_tools/__init__.py:127` |
| Bot lift | `_extract_last_linked_surface_result` membership test | `a.get("type") in {...}` | `bots/base.py:1042` |
| `SSRHTMLRenderer._render_Text` | `degradation_record(node, …)` + `<pre><code>` | new role branch | `ssr_html.py:532` |
| `AdaptiveCardsRenderer` Text | `TextBlock(fontType="Monospace", wrap=True)` + `state.degradations` | new role branch | `adaptive_cards.py:466` |
| `InteractiveHTMLRenderer._render_prim_Text` | `degradation_record` + `<pre><code>` | new role branch | `interactive_html.py:1117` |
| `A2UINode.svelte` | `A2UIMermaidDiagram` | new `{:else if}` branch | `A2UINode.svelte:250` |
| `A2UIMermaidDiagram.svelte` | `import('mermaid')`, `DOMPurify.sanitize` | lazy import + sanitize | `ECharts.svelte:110` (idiom), `package.json:38` (dompurify) |
| FEAT-755 phrase bank (future) | `MERMAID_DIAGRAM_ROUTE_KEY` / `MERMAID_DIAGRAM_ROUTE_UTTERANCES` | `from parrot.outputs.a2ui.graph import …` | `graph/__init__.py:30` (`__all__`) |

### Does NOT Exist (Anti-Hallucination)
<!-- Things that look plausible but DO NOT exist in the codebase.
     Prevents agents from inventing imports or attributes. -->
- ~~`parrot.outputs.a2ui.catalog.parrot.mermaiddiagram`~~, ~~`MermaidDiagramComponent`~~, ~~`MERMAIDDIAGRAM_SCHEMA`~~ — grep over `packages/` for `MermaidDiagram` hits nothing; the only `mermaid_source` hit is a LOCAL variable in `interactive_html.py:1727`, not a module.
- ~~`parrot.outputs.a2ui.mermaid`~~ (package) — does not exist; the codec is `parrot.outputs.a2ui.graph.mermaid` and the new utilities go next to it.
- ~~`builders.build_mermaid_diagram`~~, ~~`detect_diagram_type`~~, ~~`normalize_mermaid_source`~~, ~~`check_mermaid_source`~~, ~~`graph_spec_from_mermaid_source`~~ — new in this spec.
- ~~a per-component `validate()` hook on registered components~~ — `register_component` only enforces `lower()` (`catalog/__init__.py:160-168`); component-specific checks are hard-coded passes inside `validate_envelope` (`_validate_filter_params` `:521`, inline-data gate `:110`). Follow that pattern.
- ~~`MermaidCodecError` for sequence `loop`/`alt`/`note` *support*~~ — those constructs are rejected by the codec (`graph/mermaid.py:77-87`); `graph_spec_from_mermaid_source` inherits the rejection, it does not extend the subset.
- ~~`from_mermaid` returning `kind="dag"`~~ — never (`graph/mermaid.py:50-55`); the round-trip test compares a `dag` spec's export as `flowchart`.
- ~~`sdd/specs/inline-a2ui-component-routing.spec.md`~~ (FEAT-755) and ~~`sdd/specs/a2ui-c4-diagrams.spec.md`~~ (FEAT-754) — ids are reserved (`git log -- sdd/tasks/.id_ledger.json`: `6e47f071c`, `8f577545d`) but the specs are NOT written; do not import or cite symbols from them. The route key format `"a2ui:<Component>"` is an OPEN question of the brainstorm (`output-mode-intent-router.brainstorm.md:405`).
- ~~`IntentRouterConfig.a2ui_component_routes`~~, ~~`add_route("a2ui:MermaidDiagram", …)`~~ — not in this spec; `add_route()` takes an `OutputMode` today (brainstorm `:309`).
- ~~`MermaidDiagram` in any renderer's `supported_components`~~ / ~~`_INTERCEPTED`~~ / ~~`_render_mermaiddiagram()`~~ — deliberately not added (D5): the component always lowers on server lanes.
- ~~`"mermaid"` in `ui/package.json`~~ — absent today (`dependencies`, `:17-55`); M6 adds it.
- ~~`$lib/features.mermaid`~~ / ~~`__AGENTCHAT_MERMAID__`~~ — no new feature flag; reuse `features.a2ui` (`features.ts:31`).
- ~~`A2UIMermaidDiagram.svelte`~~, ~~`MermaidDiagramProperties`~~ — new in M6; the `canvas/a2ui/` folder holds `A2UIGraph/A2UIInfographic/A2UINode/A2UISurface` only.
- ~~`parrot.outputs.a2ui.renderers.base`~~ — no such module; `RendererCapabilities`/`AbstractA2UIRenderer` live in `renderers/__init__.py:51,78`.
- ~~a committed Parrot `catalog_definition.json`~~ — only the vendored Basic one exists (`catalog/basic/spec/catalog_definition.json`); nothing to regenerate.
- ~~`tests/bots/test_linked_surface_lifting.py::...a2ui_surface`~~ — the lift tests cover `a2ui_linked_surface` and a `{"type": "chart"}` negative (`:39-53`) only; M4 adds the positive case.

### Edit Sites (Blueprint Anchors)
<!-- One row per file the §3 modules will touch. `/sdd-task` turns each row into an
     Implementation Blueprint block, so the anchor is verified ONCE per feature here
     instead of once per task. Keep it to files the modules actually change — this
     table is re-read on every downstream turn, so rows must earn their place.

     Verified against: b9417f4a0 (2026-10-27)

     Anchors go stale between spec time and task time. `/sdd-task` MUST re-run the
     `grep -c` for every row it uses; this table saves the search, not the check. -->

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid_source.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/mermaiddiagram.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/mermaid_diagram.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIMermaidDiagram.svelte` | CREATE | — | — | — |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UIMermaidDiagram.test.ts` | CREATE | — | — | — |
| `packages/ai-parrot/tests/outputs/a2ui/graph/test_mermaid_source.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/outputs/a2ui/test_components_mermaiddiagram.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/outputs/a2ui/test_builders_mermaid.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/outputs/a2ui/golden/mermaiddiagram_lowered.json` | CREATE | — | — | — |
| `packages/ai-parrot-tools/tests/test_mermaid_diagram_tool.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py` | MODIFY | `TRANSFORM_REF_UNKNOWN = "TRANSFORM_REF_UNKNOWN"` | `catalog/base.py:96` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py` | MODIFY | `    TRANSFORM_REF_UNKNOWN,` (import block from `catalog.base`, L37-61) | `catalog/__init__.py:48` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py` | MODIFY | `        _validate_linked_sources(envelope, origin=origin, issues=issues)` | `catalog/__init__.py:964` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/__init__.py` | MODIFY | `    htmldocument,  # noqa: F401` | `catalog/parrot/__init__.py:17` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/__init__.py` | MODIFY | `__all__ = [` | `graph/__init__.py:30` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py` | MODIFY | `    "build_html_document",` (inside `__all__`, L57-69) | `builders.py:62` | 1 |
| `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py` | MODIFY | `def build_graph(` (new builder inserted immediately before it) | `builders.py:330` | 1 |
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | `                isinstance(a, dict) and a.get("type") == "a2ui_linked_surface" for a in artifacts` | `bots/base.py:1042` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | `    "publish_surface": "parrot_tools.ui_surfaces.PublishSurfaceTool",` | `parrot_tools/__init__.py:127` | 1 |
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py` | MODIFY | `        if role == "html_document":` | `ssr_html.py:532` | 1 |
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py` | MODIFY | `        if role == "html_document":` | `adaptive_cards.py:466` | 1 |
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py` | MODIFY | `    def _render_prim_Text(self, node: BasicNode, degradations: list[dict[str, Any]]) -> str:` | `interactive_html.py:1117` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UINode.svelte` | MODIFY | `{:else if component === 'HtmlDocument'}` | `A2UINode.svelte:250` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UINode.test.ts` | MODIFY | `  it('rejects a bare Graph on a Parrot-default surface (unsupported placeholder)', () => {` | `A2UINode.test.ts:239` | 1 |
| `packages/ai-parrot-server/ui/package.json` | MODIFY | `    "marked": "^15.0.4",` | `package.json:46` | 1 |
| `packages/ai-parrot/tests/outputs/a2ui/conformance/test_all_emitters.py` | MODIFY | `class TestCatalogDefinitionIncludesGraph:` | `test_all_emitters.py:555` | 1 |
| `packages/ai-parrot/tests/bots/test_linked_surface_lifting.py` | MODIFY | `def test_extract_last_linked_surface_result_ignores_non_linked() -> None:` | `test_linked_surface_lifting.py:39` | 1 |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_ssr_html.py` | MODIFY | `class TestHtmlDocumentDegradesToLink:` | `test_ssr_html.py:270` | 1 |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_interactive_html.py` | MODIFY | `class TestHtmlDocumentSandboxedIframe:` | `test_interactive_html.py:478` | 1 |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_adaptive_cards.py` | MODIFY | `class TestHtmlDocumentDegradesToTextBlockAndOpenUrl:` | `test_adaptive_cards.py:261` | 1 |
| `docs/outputs/a2ui-v1.md` | MODIFY | `| **Parrot** (this codebase's presentation layer) | \`https://parrot.dev/catalogs/v1\` | \`InfoCard\`, \`Chart\`, \`DataTable\`, \`Map\`, \`KPICard\`, \`Timeline\`, \`Infographic\`, \`Report\` |` | `a2ui-v1.md:78` | 1 |
| `docs/outputs/a2ui-v1.md` | MODIFY | `## Adaptive Cards and the Teams submit flow` (new section inserted before it) | `a2ui-v1.md:474` | 1 |
| `docs/frontend/agentdashboard-a2ui-reference.md` | MODIFY | `### 5.2 Parrot presentation catalog — 10 composites (\`catalog/parrot/*.py\`)` | `agentdashboard-a2ui-reference.md:497` | 1 |
| `docs/frontend/agentdashboard-a2ui-reference.md` | MODIFY | `alongside Basic and Parrot (§5.1/§5.2, still 10 composites — viz-core is` | `agentdashboard-a2ui-reference.md:616` | 1 |
| `docs/frontend/agentdashboard-a2ui-reference.md` | MODIFY | `## 6. Dashboards, infographics and widgets` (new §5.5 inserted before it) | `agentdashboard-a2ui-reference.md:710` | 1 |

- A **CREATE** row declares only the path the module adds; it needs no anchor.
- **Occurrences > 1** means the one-line anchor is ambiguous. Quote 2–3 lines of
  surrounding context in the anchor cell so the blueprint block can attach uniquely.
- An anchor that cannot be verified is written `(unverified — check before use)`,
  never guessed.
- `interactive_html.py` also has `        if name == "HtmlDocument":` at `:1034` and
  `:1051` (2 occurrences) — deliberately NOT an edit site (D5: no interception).

---

## 7. Implementation Notes & Constraints

> Architecture decisions stay with the thinking model. A delegated
> implementation may only express a decision already recorded here and in
> the TASK's implementation blocks — it must never invent an API, choose a
> file, or resolve an open design question.

### Patterns to Follow
- **Opaque-surface precedent**: `catalog/parrot/htmldocument.py` for file layout
  (module docstring → `SCHEMA` dict → `INSTRUCTIONS` → `@register_component` class with
  `lower()`), `builders.build_html_document` for the builder, `test_components_htmldocument.py`
  for the golden + gate tests. Differences are deliberate: not `tool_only`, no XOR, source
  IS copied into the lowered tree (it is text, not HTML).
- **Typed-vocabulary precedent for the lowered tree and renderer matrix**: `GraphComponent.lower()`
  (`catalog/viz_core/graph.py:76-153`) — description first, `parrot_variant` on the Card,
  source Text last.
- **Validation pass precedent**: `_validate_filter_params` / `_validate_linked_sources`
  (`catalog/__init__.py:521,588,740,964`) — collect into `issues`, never raise early.
- **Renderer degradation precedent**: the `html_document` role branches (`ssr_html.py:532`,
  `adaptive_cards.py:466`) — degrade visibly, record once, keep the node id.
- **Lazy import precedent (UI)**: `ECharts.svelte:110` (`fullEchartsPromise ??= import("echarts")`),
  `DataMap.svelte:124`; Svelte 5 runes only (`$props`, `$state`, `$derived`, `$effect`);
  tests with `@testing-library/svelte` + `vi.mock` (`A2UINode.test.ts:20`).
- **Tool precedent**: `parrot_tools/ui_surfaces.py` (`AbstractToolArgsSchema` + `AbstractTool`,
  `name`/`description`/`args_schema`, `async _execute(**kwargs) -> dict`), tests
  `packages/ai-parrot-tools/tests/test_publish_surface_tool.py`.
- Google-style docstrings, strict type hints, 120 columns, `self.logger`/module `logger`
  — never `print`; `black` formats, `ruff` (TID251) gates.

### LLM instructions (`MERMAIDDIAGRAM_INSTRUCTIONS`, verbatim — consumed by FEAT-755's emitter via `catalog_instructions()`)
```
MermaidDiagram shows a diagram written in Mermaid syntax: sequence, class, ER, state, flowchart, gantt,
pie, user journey, mindmap, gitGraph, timeline, quadrant, requirement, C4 and the other Mermaid diagram
types. Put the complete Mermaid text in `source` (one statement per line, the diagram keyword on the first
line, under 32 KB). Set `diagramType` to the detected type (flowchart, sequence, class, state, er, journey,
gantt, pie, quadrant, requirement, gitGraph, c4, mindmap, timeline, …) and always give
`accessibleDescription` (one sentence saying what the diagram shows). Optional `title`, `caption`, and a
`theme` hint (default, neutral, dark, forest, base). NEVER write `%%{init: …}%%` directives, `click`/`link`/
`callback` statements, `javascript:` URLs or HTML tags — the envelope is rejected. For a workflow, state
machine or dependency graph that renderers should lay out and style from typed data, prefer the viz-core
`Graph` component instead; use MermaidDiagram when the diagram type has no typed component.
```

### Default route utterances (`MERMAID_DIAGRAM_ROUTE_UTTERANCES`) — handoff to FEAT-755
EN: "as a diagram", "draw this as a diagram", "sequence diagram of", "show the flow as a sequence
diagram", "class diagram of", "ER diagram of the data model", "gantt chart of the plan", "draw a
mindmap". ES: "diagrama de secuencia de", "muéstralo como diagrama", "diagrama de clases de",
"diagrama entidad-relación", "haz un diagrama de flujo", "dibuja un mapa mental". Deliberately NOT
included: "graph", "show this as a graph" — already a `STRUCTURED_CHART` utterance
(`bots/data.py:302`); FEAT-755 owns the disambiguation between chart / `Graph` / `MermaidDiagram`.

### Degradation messages (fixed strings, asserted by tests)
- ssr-html / pdf: `"ssr-html has no Mermaid engine; source shown as a code block"`
- adaptive_cards: `"adaptive_cards has no Mermaid engine; source shown as monospace text"`
- interactive-html: `"interactive-html does not bundle mermaid.js (self-contained invariant); source shown as a code block"`

### Known Risks / Gotchas
- **Import cycle**: `catalog/__init__.py` will import `graph.mermaid_source`, which imports
  `catalog.base` and `graph.mermaid` (which already imports `catalog.base`, `graph/mermaid.py:56`).
  `catalog.base` imports only `parrot.outputs.a2ui.models` (`base.py:25`) — no cycle as
  long as `mermaid_source.py` never imports `parrot.outputs.a2ui.catalog` (the package)
  or `catalog.parrot`. Mitigation: the M1 test imports `mermaid_source` in a fresh
  interpreter first (`test_lazy_imports.py:_run_probe` idiom).
- **Lazy-import guard** (`test_lazy_imports.py:16-23,60-70`): `parrot.bots.data` must not
  pull `catalog.parrot`. The phrase-bank constants therefore live in `graph/mermaid_source.py`
  and are re-exported from `parrot.outputs.a2ui.graph`; FEAT-755 must import them from
  there, never from `catalog.parrot.mermaiddiagram`.
- **Front-matter vs directives**: Mermaid allows a YAML `---` block at the very top
  (`title:`, `config:`). `config:` in front-matter can carry the same keys as `%%{init}%%`.
  Decision: front-matter is kept verbatim (it is how Mermaid sets a title) BUT a
  `config:` key inside it is treated like a directive — stripped by `normalize_mermaid_source`
  and rejected by `check_mermaid_source` (`MERMAID_UNSAFE_DIRECTIVE`).
- **False positives in the interaction check**: `click` is matched as the FIRST TOKEN of a
  statement only, so a node labelled `clickable[Clickable button]` passes; `javascript:` and
  `<script` are matched anywhere, case-insensitively — a label containing them is rejected
  on purpose (there is no legitimate diagram use).
- **Byte cap vs. `maxLength`**: the JSON-Schema `maxLength` counts code points, the Python
  check counts UTF-8 bytes (the stricter one wins at runtime; the schema value is documentation
  for the LLM, exactly like `HtmlDocument`'s "< 50 KB" note).
- **`GraphComponent.lower()` already emits Mermaid text** under `parrot_role: "graph-source"`
  — do NOT rename it; renderers may share one helper for both roles but must keep the role
  strings distinct (docs list both).
- **Bot lift precedence** (`bots/base.py:1674-1686`): a `render_mermaid_diagram` result is
  lifted only when no interactive/infographic envelope was produced in the same turn and
  nothing set `a2ui_envelope` yet — identical to the linked lift; document this in the
  tool docstring so agents do not call it alongside an infographic render.
- **`test_no_exec.py` file-count floor** (`:85`, `>= 40`) only rises with new files — safe.
- **mermaid.js in the bundled UI**: mermaid 11 is ~2–3 MB; it MUST stay out of the main
  chunk (dynamic `import('mermaid')` — Vite splits it automatically; AC-8 verifies). jsdom
  cannot run it: every vitest MUST mock `mermaid`. `securityLevel: "strict"` sanitizes
  HTML labels through mermaid's own DOMPurify, and the rendered SVG is sanitized AGAIN with
  the app's `dompurify` (svg profile) before `{@html}` — belt and braces, because `{@html}`
  bypasses Svelte escaping.
- **Dark theme**: the SPA has no `--accent-*` tokens (`A2UIGraph.svelte:7-12`); mermaid's
  `dark`/`default` built-in themes are used instead of `themeVariables` (which would be a
  "how" leak and a CSS-injection surface).
- **Concurrent renders**: mermaid's `render(id, …)` requires unique ids per call — derive
  from a module-level counter, never from the wire component id alone (a surface can be
  re-rendered).
- **Shared venv / worktree testing**: run pytest with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src`
  inside the worktree (`.claude/rules/worktree-management.md` §4), vitest from
  `packages/ai-parrot-server/ui` with `pnpm`.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `mermaid` (npm, `packages/ai-parrot-server/ui`) | `^11.x` — pin the current 11.x release at task time (verify on npm; the only in-repo reference is the 10.9.3 CDN card at `tools/interactive/catalog/libraries/mermaid.md`, kept as-is) | native inline rendering in the bundled SPA, lazy-imported only |
| `dompurify` (npm) | already `^3.4.17` (`package.json:38`) | SVG sanitization before `{@html}` |
| Python | **none added** | validation is pure-Python string scanning; no Mermaid parser, no headless browser |

---

## Worktree Strategy

- **Isolation**: `per-spec` — one worktree `feat-FEAT-753-a2ui-mermaid-diagram` from
  `origin/dev` (`python -m scripts.sdd.ensure_worktree --slug a2ui-mermaid-diagram --feature-id FEAT-753`),
  tasks sequential in dependency order M1 → M2 → M3 → (M4 ‖ M5 ‖ M6) → M7.
- **Parallelizable inside the worktree**: after M1–M3 land, M4 (tools + bot lift), M5
  (satellite renderers) and M6 (bundled UI) touch disjoint files.
- **Cross-feature dependencies**:
  - **FEAT-755 `inline-a2ui-component-routing` — LLM lane only.** The builder/tool lane
    (M1–M7) has NO dependency on it and can merge first. FEAT-755 must merge before any
    LLM can *route* to `MermaidDiagram`; it consumes `MERMAIDDIAGRAM_SCHEMA`/`INSTRUCTIONS`
    (via `catalog_instructions`) and `MERMAID_DIAGRAM_ROUTE_KEY`/`MERMAID_DIAGRAM_ROUTE_UTTERANCES`
    from this feature, so **this feature merges first** (or FEAT-755 bases on this branch).
  - **FEAT-754 `a2ui-c4-diagrams`** is independent; it may later map `diagramType: "c4"`
    sources to a typed kind — no shared files.
  - **FEAT-752 / FEAT-756**: no shared files.
- **Shared-file watch**: `catalog/__init__.py`, `catalog/base.py`, `builders.py`,
  `bots/base.py`, `A2UINode.svelte`, `docs/outputs/a2ui-v1.md` are touched by most A2UI
  features — rebase on `origin/dev` before opening the PR and re-run the `grep -c` checks
  in §6.

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [ ] **Q1 — Route key format.** `MERMAID_DIAGRAM_ROUTE_KEY = "a2ui:MermaidDiagram"` assumes
  FEAT-755 picks string composite keys inside `output_mode_routes` (brainstorm `:405` leaves
  this open vs. a parallel `a2ui_component_routes` field). The utterance tuple is format-agnostic;
  only the key constant may need renaming when FEAT-755 is specified. — *Owner: Jesus Lara (FEAT-755 author)*
- [ ] **Q2 — `MERMAID_SOURCE_MAX_BYTES = 32 KiB`.** Large ER/class diagrams of real schemas can
  exceed it. Keep 32 KiB (an inline bubble) or 64 KiB? Resolvable in task M1 without design
  change (one constant + schema `maxLength`). — *Owner: Jesus Lara*
- [ ] **Q3 — Interactive-HTML lane with a vendored mermaid bundle.** D5 keeps the lane on the code
  block. If a vendored, SRI-pinned `mermaid.min.js` under `formats/assets/` (like Chart.js) is
  acceptable (~2.5 MB per artifact), a follow-up could intercept `MermaidDiagram` there. Not in
  scope; record the decision. — *Owner: Jesus Lara*
- [ ] **Q4 — Should `diagramType: "unknown"` be rejected for `origin=LLM`?** Today it is allowed
  for both origins (mermaid.js may support a dialect the Python table does not know). Rejecting
  it for LLM would tighten the retry loop at the cost of a maintenance coupling to mermaid releases.
  Default: allow. — *Owner: Jesus Lara*
- [ ] **Q5 — Tool name.** `render_mermaid_diagram` vs `mermaid_diagram`. The mapping key is
  `mermaid_diagram`; the LLM-facing `name` is `render_mermaid_diagram` (verb-first like
  `publish_surface`). Confirm before M4. — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `<model>` · Status: completed | skipped (<reason>)
> · Transcript: `sdd/state/<FEAT-ID>/design_research/`
> Every row is a suggestion the reviewer made; the disposition is the spec author's
> call (CONFIRM = folded into the spec, REJECT = reason recorded, ESCALATE = §8 question).

Status: skipped (no accepted exploration document — spec authored from the NAV-10382 ticket review)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-27 | Jesus Lara | Initial draft from the NAV-10382 review; codebase contract verified against `b9417f4a0` |
