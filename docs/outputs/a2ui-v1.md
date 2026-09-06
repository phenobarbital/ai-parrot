# A2UI v1.0 Wire (FEAT-470)

`parrot.outputs.a2ui` implements the **A2UI v1.0** wire protocol
(`google/A2UI` `specification/v1_0`, pinned commit `90157ec1`) end to end:
Pydantic models that *are* the wire shape, a vendored + `jsonschema`-validated
official Basic Catalog (18 primitives, 14 functions), a Parrot presentation
catalog layered on top, and six static/interactive renderers in the
`ai-parrot-visualizations` satellite.

This page documents the wire as implemented in this codebase. For the
dialect → v1.0 migration story (breaking changes, `Card`→`InfoCard`, recipe
schema bump), see
[`docs/migration/feat-273-a2ui-deprecations.md`](../migration/feat-273-a2ui-deprecations.md).

## The envelope

Every A2UI message on the wire is an **envelope by key**: exactly `version`
plus one message key.

```json
{"version": "v1.0", "createSurface": {"surfaceId": "main", "catalogId": "https://parrot.dev/catalogs/v1", "components": [...]}}
```

- **Agent → Renderer** (`A2UIAgentMessage`): `createSurface`,
  `updateComponents`, `updateDataModel`, `deleteSurface`,
  `callRendererFunction`, `agentFunctionResponse`.
- **Renderer → Agent** (`A2UIRendererMessage`): `action`,
  `callAgentFunction`, `rendererFunctionResponse`, `error`.

`version` is written in exactly one place — `parrot.outputs.a2ui.serialization.serialize`
(spec invariant G3) — never by the message models themselves. `deserialize`
accepts both the v1.0 envelope-by-key shape and the legacy pre-v1.0 dialect
(`messageType`/nested `properties`/`$bind`), normalizing the latter via
`parrot.outputs.a2ui.compat.normalize_legacy` with a `DeprecationWarning`.
Compat is **read-only**: nothing in this codebase ever emits the legacy
shape, and there is no dual-emission flag.

## The Component shape

```python
class Component(BaseModel):          # extra="allow" — catalog props live top-level
    id: str
    component: str
    catalog_id: str | None            # alias catalogId
    child: str | None                 # single-child reference (by id)
    children: list[str] | ChildTemplate | None   # multi-child list, OR a template
    weight: float | None
    accessibility: AccessibilityAttributes | None
    checks: list[CheckRule] | None
    action: Action | None
    metadata: ComponentMetadata | None
```

Catalog-specific properties (`text`, `title`, `layers`, ...) sit **top-level**
on the component dict, not nested under a `properties` key — this is the
single biggest wire-shape change from the pre-v1.0 dialect. A dynamic value
anywhere in a component's props is one of:

- a literal (`"Hello"`, `42`, `true`, ...),
- a data binding: `{"path": "/pointer"}` (RFC 6901 JSON Pointer, absolute or
  scope-relative inside a template), or
- a function call: `{"call": "formatString", "args": {...}}`.

`children` is either a plain list of child ids, or a **template**:
`{"componentId": "<source-id>", "path": "/list/pointer"}` — the renderer (or
`baking.bake_envelope`) clones the referenced source component once per item
in the bound list, resolving `@index` inside the clone.

Every `CreateSurface`'s component list carries exactly one component with
`id: "root"` (spec G6) — `builders.build_surface` (and everything built on
it) guarantees this automatically.

## Three catalogs, one resolution rule

| Catalog | `catalogId` | Contents |
|---|---|---|
| **Basic** (official) | `https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json` | 18 primitives + 14 functions, vendored verbatim under `catalog/basic/spec/*.json` (SHA-pinned: `catalog/basic.SPEC_COMMIT`) |
| **Parrot** (this codebase's presentation layer) | `https://parrot.dev/catalogs/v1` | `InfoCard`, `Chart`, `DataTable`, `Map`, `KPICard`, `Timeline`, `Infographic`, `Report` |
| **viz-core** (FEAT-529) | `https://ai-parrot.dev/a2ui/catalogs/viz-core/1.0/catalog.json` | `Graph` today; a library-agnostic, "describe what, never how" visualization vocabulary shared with future components (charts, live surfaces) |

`catalog.export_catalog_definition()` produces a catalog's own
`catalog_definition.json`-shaped document (valid against the vendored
official schema of the same name) — every Basic Catalog component/function
is included there as a `$ref` (`{"$ref": "<BASIC_CATALOG_ID>#/components/Text"}`)
rather than duplicated, so **a bare component name resolves under either
catalog** without an explicit `catalogId` per component
(`catalog.resolve_catalog`: component's own `catalogId` wins, else the
surface's default). A component naming neither resolves to
`CATALOG_UNRESOLVED`. The registry (`_CATALOG`) is keyed by
`(catalog_id, name)` — `catalog.get_component(name, catalog_id=None)`
resolves the unique match when `catalog_id` is omitted and raises
`CatalogError` (naming the candidates) only once a name is genuinely
ambiguous across catalogs (not yet the case for any name in this codebase).

A surface's default is always `catalogId: "https://parrot.dev/catalogs/v1"`
(every public builder sets this) — so `Text`, `Button`, and the rest of the
Basic Catalog are usable directly inside a Parrot-catalog surface with no
extra ceremony. A `Graph` component instead carries its OWN explicit
`catalogId: "https://ai-parrot.dev/a2ui/catalogs/viz-core/1.0/catalog.json"`
— the surface stays Parrot-default; only the component overrides.

### viz-core principles (FEAT-529)

viz-core's rule is **describe what, never how**: no colour, font, pixel
size, or renderer-library option ever appears on the wire.

- **Semantic colour roles, not values.** A viz-core component's *data*
  (e.g. `Graph.nodes[].state`) stays a domain enum; the RENDERER contract
  (not the schema) maps it to a semantic status role (`good`/`warning`/
  `critical`/`primary`/`neutral`) and paints that role with its own theme
  tokens (`DesignSystem` CSS custom properties server-side, this app's own
  shadcn/Tailwind tokens in the bundled UI).
- **Semantic formats, never printf strings.**
- **Size is layout intent, never pixels** — `inline`/`tile`/`hero`, each
  renderer maps these to its own container class/dimensions.
- **`accessibleDescription` on every visual** — the screen-reader summary
  and the lowered fallback's/static SVG's first line.
- **The standard `action`** is the ONLY interaction primitive — no
  component-specific `selectAction`/`nodeAction` prop.
- **Layout is server-side preparation, not styling** — when a viz-core
  component computes positions (e.g. `Graph.layout.positions`), those
  travel on the wire so every renderer draws the same picture; a renderer
  computes them itself only when they are absent.

### `lower()` — Parrot components become Basic primitives

Every non-primitive, registered component MUST implement
`lower(self, component, data_model) -> BasicNode` (enforced at
`register_component()` time — spec invariant G4; the 18 Basic Catalog
primitives are the only components registered with `is_primitive=True`,
exempting them). `lower()` returns a nested `BasicNode` tree built entirely
from Basic Catalog primitives; `catalog.base.to_components()` flattens that
tree into the wire's flat, id-adjacency-list shape.

This is what every satellite renderer actually consumes: renderers dispatch
on Basic Catalog component names, never on `Chart`/`InfoCard`/etc. directly —
lowering happens first (see e.g. `SSRHTMLRenderer._lower_composites`), then
baking resolves bindings.

## `metadata.extensions` — presentation semantics live outside the schema

Anything that is presentation semantics rather than official A2UI wire
vocabulary — a `Text`'s stylistic role, which renderer variant a lowered
`Card` represents, whether a binding is allowed to be absent — is carried in
`metadata.extensions`, never as a bare top-level prop the official schema
doesn't know about (spec G4). Keys follow UAX #31 identifier syntax; `a2ui_`
is reserved for official extensions, so this codebase's own keys are always
`parrot_*`:

| Key | Meaning |
|---|---|
| `parrot_role` | Presentation role of a lowered `Text` (`"title"`, `"caption"`, `"label"`, `"value"`, `"delta"`, `"axis"`, `"series"`, `"event-title"`, `"notice"` (a degradation placeholder), ...) |
| `parrot_variant` | Which Parrot component a lowered `Card` stands in for (`"chart"`, `"kpi"`, `"infocard"`, ...) |
| `parrot_component_id` | The original (pre-lowering) Parrot component's own id, when a lowered subtree needs to remember it |
| `parrot_optional` | A list of pointers (`baking.bake_envelope` reads this off a component's own metadata) that may fail to resolve at bake time WITHOUT raising `BakeError` — the key is simply omitted from the baked output |
| `parrot_unit`, `parrot_trend`, `parrot_series_data`, ... | Component-specific presentation hints (KPICard's unit/trend, a lowered Chart series' original binding, ...) |

`metadata.extensions` validates against the official
`common_types.json#/$defs/Extensions` (`patternProperties` on the UAX #31
identifier pattern, `additionalProperties: false` — i.e. keys must match that
pattern and nothing else is allowed at that level).

> **Implementation note**: the vendored `Extensions` pattern uses a
> PCRE/ECMA-style `\p{XID_Start}`/`\p{XID_Continue}` Unicode property escape
> that Python's stdlib `re` module cannot compile. `catalog.validate_message`
> works around this by swapping in the `regex` package (drop-in `re`-API
> compatible, supports `\p{}`) for the duration of one validation call when
> importable — see `catalog._unicode_aware_jsonschema`'s docstring.

## Validation

- **`catalog.validate_envelope(envelope, *, origin, surface_catalog_id=None)`**
  — the catalog-level structural check every builder runs internally:
  resolves every component's `catalogId`, confirms exactly one `root`, no
  duplicate ids, no dangling `child`/`children` references,
  `allowedParents`/`allowedChildren` (when a component declares them), and —
  for `origin=ProducerOrigin.LLM` — that no component carries an `action` or
  is `requires_actions=True` (D10b: the LLM producer path can never emit an
  action-bearing envelope). Reports every problem found, not just the first,
  so a retry loop can address all of them at once.
- **`catalog.validate_message(message)`** — the literal `jsonschema`
  validation of a full envelope against the vendored, SHA-pinned
  `agent_to_renderer.json` / `renderer_to_agent.json`. Note: the official
  schema's `Component` definition resolves `catalog.json#/$defs/anyComponent`
  against the **Basic Catalog only** (that is how the upstream schema is
  written — one pinned catalog, not "any registered catalog") — so a
  Parrot-catalog envelope (`InfoCard`/`Chart`/...) validates in its
  **lowered** form, exactly like a renderer would receive it. The
  conformance suite (`tests/outputs/a2ui/conformance/test_all_emitters.py`)
  demonstrates this two-layer pattern for every emission point in the
  codebase (builders, the Infographic adapter, a producer-shaped fixture,
  recipes, `bake_envelope` output, and each renderer's input envelope).

## Baking — resolving bindings for static output

`baking.bake_envelope(envelope) -> list[dict]` resolves every `{"path"}` and
evaluates every `{"call"}` against the envelope's `dataModel`, expands every
template `children` into one clone per bound list item (with `@index`
resolved and ids suffixed `-<i>`), and asserts the post-condition that zero
live bindings survive. `catalog.basic.functions.FunctionEvaluator`
implements all 14 official functions (`formatString` with `${/path}`,
`${fn(arg:'v')}`, and `\${` escaping; the boolean combinators `and`/`or`/`not`;
the validators `required`/`regex`/`length`/`numeric`/`email`, each returning
a `ValidationResult`; `openUrl`, marked `requiresUserActivation`).

## Renderers and degradation

Six renderers ship from `ai-parrot-visualizations` (`parrot.outputs.a2ui_renderers`),
registered against the core `parrot.outputs.a2ui.renderers` registry:
`ssr_html`, `pdf` (weasyprint, extends `ssr_html`), `interactive_html`,
`echarts`, `folium_map`, `adaptive_cards`. Each declares
`RendererCapabilities.supported_components` — the Basic Catalog names it
natively renders. Anything else is **degraded, never raised**
(`renderers.degrade.degrade()` swaps in a visible `Text` placeholder; every
renderer collects one `{"id", "component", "reason"}` record per degradation
into `RenderedArtifact.metadata["degraded"]`, via `degrade.degradation_record()`).
For example, `PDFRenderer` inherits `SSRHTMLRenderer`'s primitive set minus
`Video`/`AudioPlayer` (a rasterized PDF cannot play media — both degrade to a
link).

## `Graph` — the viz-core workflow/state-machine component (FEAT-529)

`Graph` renders a workflow, state machine, dependency graph, or call
sequence as TYPED `nodes[]`/`edges[]` — never a mermaid string on the wire
(mermaid is a pure-Python codec, both ways, for import/export/documentation
only: `parrot.outputs.a2ui.graph.{to_mermaid,from_mermaid}`).

```python
# parrot/outputs/a2ui/graph/models.py — GraphSpec (single source of vocabulary)
kind: "flowchart" | "state" | "sequence" | "dag"   # dag rejects cycles
direction: "TB" | "LR" | "BT" | "RL"
title, accessibleDescription, size: "inline" | "tile" | "hero"   # viz-core common props
nodes: [{id, label?, shape?, group?, state?, icon?, meta?}]
edges: [{from, to, label?, kind?, condition?}]
groups: [{id, label?, nodes: [id, ...]}]
layout: {engine: "layered" | "force" | "manual", rankSep?, nodeSep?, positions?}
selection: {selectable?, selected?}
data: {"path": "/pointer"}   # binding descriptor on the wire; overlays state/label/meta per node id
action: <the standard v1.0 Action>   # TOOL origin only — see below
```

`GRAPH_SCHEMA` (`catalog/viz_core/graph.py`) is derived from `GraphSpec` via
`derive_schema` (schema parity by construction, same pattern as `Chart`),
plus one explicit merge: `action` is not a `GraphSpec` field (nor part of
the official `common_types.json#/$defs/ComponentCommon`) — it is declared
as a `$ref` to the vendored `common_types.json#/$defs/Action`.

Node `shape`: `rect` (default), `rounded`, `diamond`, `circle`, `hexagon`,
`subroutine`. Edge `kind`: `solid` (default), `dashed`, `thick`.

### Node state → semantic status role → theme token

`state` is DATA (a domain enum: `pending`/`running`/`completed`/`failed`/
`skipped`/`waiting`), never styling. Every renderer maps it to a viz-core
semantic status role, then paints that role with its own theme:

| `state` | status role | `DesignSystem` token (static/server lanes) |
|---|---|---|
| `completed` | `good` | `--accent-green` |
| `waiting` | `warning` | `--accent-amber` |
| `failed` | `critical` | `--accent-red` |
| `running` | `primary` | `--primary` |
| `pending`, `skipped` | `neutral` | `--neutral-muted` |

(The bundled `ai-parrot-server/ui` SPA maps the same five roles to its own
shadcn/Tailwind tokens instead — `--chart-2`/`--chart-3`/`--destructive`/
`--primary`/`--muted-foreground` — since it has no `--accent-*`/
`--neutral-muted` custom properties of its own.)

### Node click — the standard `action`, not a bespoke prop

A `Graph` may carry the standard component-level `action` (same as
`Button`), declared explicitly in `GRAPH_SCHEMA` since it is not part of
the official `ComponentCommon`. The existing D10b gate applies unchanged:
an LLM-origin envelope carrying a `Graph` with `action` set fails
`validate_envelope` (`ACTION_NOT_ALLOWED_FOR_LLM`) — only a deterministic
TOOL producer (`build_graph(action=...)`) may set it. Renderers that
support actions add `context.nodeId`/`context.nodeLabel` when dispatching
from a node click. There is no `selectAction`/`nodeAction` — this is the
one deliberate difference from the original viz-core design draft.

### Lowered fallback

Every lane without a native drawing surface (or without viz-core in its
`supported_catalog_ids`) still shows something readable and copyable — a
`Card{Column[...]}` tree of Basic primitives:

| Order | Node | `metadata.extensions.parrot_role` |
|---|---|---|
| 1 | `Text` | `description` — `accessibleDescription`, or a generated `"Graph of N nodes and M edges (<kind>)"` |
| 2 | `Text` (if `title` set) | `title` |
| 3 | `Text` | `caption` — `"Graph (<kind>, <direction>)"` |
| 4 | `Column` | `edge-list` — one child `Text` per edge (`parrot_role: edge`, `"<from> → <to> (<label>)"`, plus `parrot_edge_kind`/`parrot_condition` when set); carries `parrot_graph_data` (the UNRESOLVED `data` binding, same convention as `Chart`'s `parrot_series_data`) when `data` is bound |
| 5 | `Text` | `graph-source` — `to_mermaid(spec)` |

The whole `Card` carries `metadata.extensions.parrot_variant == "graph"`.

### Mermaid codec subset

`parrot.outputs.a2ui.graph.{to_mermaid,from_mermaid}` is a hand-written,
dependency-free codec (no `mermaid`/`dagre`/`elkjs` package) for exactly
three dialects, matching `kind`:

- **`flowchart`** (also used for `kind="dag"` on export — a DAG is an
  acyclic flowchart; `from_mermaid` never infers `"dag"` back from text):
  all 6 node shapes, all 3 edge kinds, labels via `-- text -->` (parse-only)
  and `-->|text|` (canonical emit), `subgraph id [label] ... end` groups.
- **`stateDiagram-v2`**: `[*] --> A` / `A --> [*]` synthetic
  `__start__`/`__end__` circle nodes, `A --> B : label` transitions,
  `state "label" as id` aliases, composite `state X { ... }` groups.
- **`sequenceDiagram`**: `participant A as Label` aliases, `A->>B: msg`
  (solid) / `A-->>B: msg` (dashed) messages, in `edges[]` order.

Unsupported constructs (`classDef`, `click`, `style`, `linkStyle`,
`%%{init}` directives, `loop`/`alt`/`par` blocks, other mermaid dialects)
raise `MermaidCodecError` (a `CatalogValidationError` subclass — the LLM
producer's existing validate-retry-degrade loop needs no new plumbing)
naming the offending line. `accessibleDescription`/`size` have no mermaid
representation and are dropped on export.

### Layout — `graph/layout.py`

`compute_positions(spec, *, rank_sep=80.0, node_sep=40.0) -> LayoutResult`
is a pure, deterministic layered layout (rank assignment via longest-path
over a cycle-broken edge set, barycentre crossing reduction, integer
coordinate assignment scaled at the end) — used by `builders.build_graph`
at build time (so every renderer, including the bundled UI's `layout:
"none"` path, draws from the SAME positions) and by any renderer when
`layout.positions` is absent or incomplete. Graphs above
`MAX_STATIC_NODES` (200) raise `GraphTooLargeError`; static lanes catch it
and degrade to a truncated, readable edge list. `layout.engine: "force"` is
an interactive-renderer-only hint — every static lane degrades it to the
deterministic layered layout instead, with a recorded `degraded` entry.

### Renderer matrix

| Renderer | viz-core? | Behaviour |
|---|---|---|
| `echarts` | ✓ | Native `graph` series, `layout: "none"` with positions (falls back to the option's own layout when absent) |
| `interactive-html` | ✓ | Inline `<svg>` (shared `_graph_svg.render_graph_svg`) + a collapsed `<details><summary>Mermaid source</summary>` |
| `ssr_html` | ✓ | Inline `<svg>` |
| `pdf` | ✓ | Inline `<svg>` (inherited from `ssr_html`; weasyprint rasterizes it, no JS) |
| `adaptive_cards` | ✗ | Lowers via `GraphComponent.lower()`; records ONE `degraded` entry naming the viz-core catalog id |
| `folium_map` | ✗ | Not rendered; records ONE `degraded` entry naming the viz-core catalog id (same "single focal component" convention as any other sibling component this Map-only renderer skips) |

The bundled `ai-parrot-server/ui` SPA (behind `features.a2ui`) also
dispatches `Graph` NATIVELY — but only when the component resolves (its own
`catalogId`, else the surface default) to the viz-core catalog id; a bare
`Graph` on a Parrot-default surface falls through to the same unsupported
placeholder any other unknown component gets. See
[`docs/frontend/agentdashboard-a2ui-reference.md`](../frontend/agentdashboard-a2ui-reference.md)
§5.4 for the frontend-facing reference.

## Infographics: dual emission (FEAT-527)

`InfographicToolkit` (`parrot.tools.infographic_toolkit`, ai-parrot core)
defaults to `emit_a2ui=True`: every render — typed blocks (`render()`), the
trusted Jinja lane (`render_template()`), and the data-splice lane
(`render_data_template()`) — produces **both** the documented HTML artifact
(`html_url`/`html_inline`) **and** a validated A2UI v1.0 envelope
(`InfographicRenderResult.a2ui_envelope`). The HTML lane is a **permanent
sibling emission**, not a deprecated path (amends FEAT-273 G7 — see
`sdd/specs/a2ui-implementation.spec.md`).

- **`AgentTalk` JSON contract**: an `output_mode: "infographic"` turn gains
  one additive `a2ui_envelope` key (omitted when the build failed —
  additive-lane policy, never breaks the HTML response); an
  `output_mode: "a2ui"` turn gains `metadata.html_url`/`artifact_id`/
  `template_name`/`theme` so an HTML-only consumer can still iframe the
  sibling artifact.
- **Typed blocks** (`render()`) lower to the `Infographic` composite
  (KPICard/Chart/DataTable/… sections), same as before FEAT-527.
- **The Jinja lane** (`render_template()`/descriptor-less
  `render_data_template()`) no longer builds a synthetic title+summary
  `Infographic` envelope. It wraps the rendered, trusted HTML as an opaque
  `HtmlDocument` component instead — see below.
- **Presentation parity** (FEAT-527 Module 2): the `Chart` schema accepts
  `donut`/`radar` without collapsing them, plus 5 new types (`gauge`,
  `funnel`, `waterfall`, `heatmap`, `treemap`); the adapter forwards
  `colorBySign`/`positiveColor`/`negativeColor`/`palette`/`trendline`/
  `layout`, table `style`, and hero-card `icon`/`color`/`comparisonPeriod`.
  `Infographic.lower()` groups consecutive `layout:"half"` children into a
  `Row`. ECharts renders the 5 new types natively; `interactive-html`/
  `ssr-html` degrade them to `bar` with a recorded `degraded` entry (never
  silent).

### `HtmlDocument` — the opaque HTML surface

A new Parrot catalog component, `tool_only=True` (same gate mechanism as
`requires_actions`): an LLM-origin envelope containing it fails
`validate_envelope`, since it carries **raw, trusted HTML** that must never
be LLM-authorable.

```python
# parrot/outputs/a2ui/catalog/parrot/htmldocument.py
{"title": str, "html": str | None, "srcUrl": str | None, "theme": str | None}
# oneOf: exactly one of html/srcUrl. build_html_document(...) enforces the
# XOR in Python and always emits with origin=ProducerOrigin.TOOL.
```

`HtmlDocumentComponent.lower()` never copies the raw HTML into the lowered
Basic Catalog tree — it degrades to a titled placeholder
(`metadata.extensions.parrot_role == "html_document"`, `parrot_src_url`,
`parrot_inline_html`). Renderer handling:

- **`interactive-html`**: intercepts `HtmlDocument` before lowering (its own
  `html`/`srcUrl` props) and embeds it in a sandboxed
  `<iframe sandbox="allow-scripts" srcdoc=…|src=…>` — never
  `allow-same-origin`, so the embedded document cannot reach the host
  DOM/storage.
- **`ssr-html`/`pdf`/`adaptive_cards`**: cannot embed HTML statically —
  degrade to a titled link (`<a href="{srcUrl}">{title}</a>`) when a
  `srcUrl` exists, else the placeholder text; always recorded in
  `metadata["degraded"]`.

## Adaptive Cards and the Teams submit flow

`AdaptiveCardsRenderer` maps input primitives to **native** Adaptive Card
inputs rather than degrading them: `TextField→Input.Text`,
`CheckBox→Input.Toggle`, `ChoicePicker→Input.ChoiceSet`, `Slider→Input.Number`,
`DateTimeInput→Input.Date`/`Input.Time`. An `Input`'s `id` is the field's own
binding `path` (e.g. `/form/email`), so the card's returned `value` map can
be applied directly as a partial `dataModel` update.

A `Button` with `action.event` becomes a top-level `Action.Submit` whose
`data` is:

```json
{"a2ui_action": {"<the v1.0 action envelope>": "..."}, "surfaceId": "main"}
```

— i.e. the **same** `A2UIRendererMessage.action` shape a live A2UI renderer
would send back over any other transport, just carried inside a Teams
Adaptive Card submit payload. A `Button` whose action is a `functionCall`
named `openUrl` becomes a top-level `Action.OpenUrl` instead. Deep links
(channel-resume actions minted by `DeepLinkService`) render as plain display
text — never `Action.OpenUrl` — since they resume a *different* conversation
context than an in-card submit.

The Microsoft Teams wrapper (`parrot.integrations.msteams.wrapper`) routes
`turn_context.activity.value["a2ui_action"]` (alongside the pre-existing
`"a2ui_token"` deep-link-resume path) into the same structured-turn handling
as a deep-link resume — the bot sees `{"type": "a2ui_action", "action": <the
action envelope>, "values": {...remaining submitted fields...}}`.

The runtime RPC loop this submit flow ultimately feeds — `callAgentFunction`
dispatch to tools, `agentFunctionResponse` correlation, `agent_capabilities`
on the Agent Card — now ships as **FEAT-469**
(`a2ui-agent-functions`); see
[`docs/outputs/a2ui-agent-functions.md`](a2ui-agent-functions.md). The Teams/
Telegram/deep-link-resume paths described above are unchanged by it — an
Adaptive Card submit is still received as a structured bot turn through
that same machinery, now additionally routed through
`A2UIRuntime.dispatch(..., transport="deeplink")` so it persists surface
state identically to a live A2UI RPC round-trip.

## A2A transport

`parrot.a2a.models`: `A2UI_EXTENSION_URI = "https://a2ui.org/a2a-extension/a2ui/v1.0"`,
`A2UI_MEDIA_TYPE = "application/a2ui+json"` — carried as
`Part.metadata["mimeType"]` on the `DataPart` an `Artifact.from_a2ui_envelope`
produces. `handlers/agent.py` exposes the sobre (or a JSONL list, when a turn
produces several) as `a2ui_envelope` in both the streaming and non-streaming
response shapes.

## See also

- [`a2ui-agent-functions.md`](a2ui-agent-functions.md) (FEAT-469) — the RPC
  leg: `callAgentFunction`/`callRendererFunction` dispatch, `sendDataModel`,
  and the HTTP/A2A/deep-link transports built on this wire.
- `docs/migration/feat-273-a2ui-deprecations.md` — dialect → v1.0 migration,
  legacy `OutputMode` deprecations, recipe schema bump.
- `sdd/specs/a2ui-v1-dialect.spec.md` (FEAT-470) — the full design spec this
  page summarizes.
- `packages/ai-parrot/tests/outputs/a2ui/conformance/` — the conformance
  suite validating every emission point against the vendored wire schemas.
