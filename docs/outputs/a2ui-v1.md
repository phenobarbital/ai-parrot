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

## Two catalogs, one resolution rule

| Catalog | `catalogId` | Contents |
|---|---|---|
| **Basic** (official) | `https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json` | 18 primitives + 14 functions, vendored verbatim under `catalog/basic/spec/*.json` (SHA-pinned: `catalog/basic.SPEC_COMMIT`) |
| **Parrot** (this codebase's presentation layer) | `https://parrot.dev/catalogs/v1` | `InfoCard`, `Chart`, `DataTable`, `Map`, `KPICard`, `Timeline`, `Infographic`, `Report` |

`catalog.export_catalog_definition()` produces the Parrot catalog's own
`catalog_definition.json`-shaped document (valid against the vendored
official schema of the same name) — every Basic Catalog component/function
is included there as a `$ref` (`{"$ref": "<BASIC_CATALOG_ID>#/components/Text"}`)
rather than duplicated, so **a bare component name resolves under either
catalog** without an explicit `catalogId` per component
(`catalog.resolve_catalog`: component's own `catalogId` wins, else the
surface's default). A component naming neither resolves to
`CATALOG_UNRESOLVED`.

A surface's default is always `catalogId: "https://parrot.dev/catalogs/v1"`
(every public builder sets this) — so `Text`, `Button`, and the rest of the
Basic Catalog are usable directly inside a Parrot-catalog surface with no
extra ceremony.

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
