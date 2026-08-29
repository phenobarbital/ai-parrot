# FEAT-273 — Legacy output-mode deprecations → A2UI

The A2UI rendering pipeline (`OutputMode.A2UI`, `parrot.outputs.a2ui`) supersedes the
ad-hoc legacy renderers. Per **G7 (coexist + deprecate)**, the legacy modes keep working
**unchanged** — but `parrot.outputs.formats.get_renderer(mode)` now emits a
`DeprecationWarning` for the replaced modes, naming the A2UI replacement. Removal is a
later feature.

## Deprecated modes → A2UI replacement

| Legacy `OutputMode` | A2UI replacement |
|---|---|
| `ALTAIR`, `PLOTLY`, `MATPLOTLIB`, `SEABORN`, `ECHARTS`, `STRUCTURED_CHART` | `OutputMode.A2UI` + **Chart** catalog component |
| `MAP`, `STRUCTURED_MAP` | `OutputMode.A2UI` + **Map** catalog component |
| `TABLE`, `STRUCTURED_TABLE` | `OutputMode.A2UI` + **DataTable** catalog component |
| `CARD` | `OutputMode.A2UI` + **InfoCard** / **KPICard** catalog components |
| `TEMPLATE_REPORT`, `JINJA2` | `OutputMode.A2UI` + **Report** catalog component |
| `HTML`, `APPLICATION` | `OutputMode.A2UI` + **SSR-HTML** renderer |
| infographic **HTML** path (`get_infographic_html_renderer`) | `OutputMode.A2UI` + **Infographic** component + SSR-HTML renderer |

## Kept (NO warning)

`JSON`, `YAML`, `MARKDOWN`, `SLACK`, `WHATSAPP`, `TERMINAL`, `DEFAULT`, and the
infographic **JSON** path (`get_renderer(OutputMode.INFOGRAPHIC)`).

## Notes

- Warnings fire only at the single lazy-load choke point
  (`parrot.outputs.formats.get_renderer`) and the infographic-HTML seam — never in
  `bots/base.py`, `OutputFormatter`, or the handlers.
- Rendering output for every legacy mode is byte-identical to before; only warnings
  were added.
- Modes with no registered renderer (`CHART`, `INTERACTIVE`, `CODE`, `IMAGE`, …) are
  untouched and still raise `ValueError` from `get_renderer`.

## FEAT-470 — the A2UI dialect → v1.0 migration

FEAT-273 (and its FEAT-301/324/326/420/430 derivatives) built the A2UI
pipeline against a **dialect** that declared itself A2UI v1.0
(`A2UI_VERSION = "1.0"`) but did not match the official wire
(`google/A2UI` `specification/v1_0`). **FEAT-470** closes that gap: every
message this codebase emits is now the genuine v1.0 wire (envelope-by-key,
`version: "v1.0"`, top-level component props). Full technical reference:
[`docs/outputs/a2ui-v1.md`](../outputs/a2ui-v1.md).

### Envelope shape

| Dialect (pre-FEAT-470) | v1.0 (FEAT-470) |
|---|---|
| `{"messageType": "createSurface", "surfaceId": ..., "version": "1.0"}` | `{"version": "v1.0", "createSurface": {"surfaceId": ...}}` — envelope-by-key |
| Component props nested under `properties: {...}` | Props **top-level** on the component dict |
| `{"$bind": "/ptr", "optional": true}` | `{"path": "/ptr"}`; the optional marker moves to the component's own `metadata.extensions.parrot_optional` list |
| `updateDataModel.contents: {a: 1, b: 2}` | One `updateDataModel` message per key: `{"path": "/a", "value": 1}`, `{"path": "/b", "value": 2}` |
| `actionResponse`, `callFunction` (0.9.1 name) | Not part of the v1.0 wire; replaced by the full v1.0 message set (`deleteSurface`, `callRendererFunction`, `agentFunctionResponse`, `callAgentFunction`, `rendererFunctionResponse`, `error`) |
| No `root` component required | Every `createSurface` carries exactly one component with `id: "root"` |

**Compatibility is read-only.** `parrot.outputs.a2ui.serialization.deserialize`
detects and normalizes a dialect payload
(`parrot.outputs.a2ui.compat.normalize_legacy`) with a `DeprecationWarning`;
nothing in this codebase emits the dialect anymore, and there is no
emission-mode flag to opt back into it. If you have code that constructs
dialect JSON by hand, switch it to the builders (`parrot.outputs.a2ui.builders`)
or the `Component`/`CreateSurface` models directly — both always produce
v1.0.

### `Card` → `InfoCard`

The dialect's own `Card` catalog component is renamed **`InfoCard`** — `Card`
is now the *official* Basic Catalog container primitive
(`catalogId: "https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json"`),
and reusing that name for the presentation component would collide with it.

- `builders.build_card(...)` — same public function name and signature, now
  emits an `InfoCard` component.
- `compat.normalize_legacy` maps a legacy `Card` payload (detected by its
  nested `properties`, distinct from a legitimate v1.0 `Card` primitive
  which uses `child`) to `InfoCard` on read, with the same
  `DeprecationWarning`.
- Any code checking `component.component == "Card"` for the presentation
  card must be updated to check for `"InfoCard"` instead.

### Recipes: `LayoutSpec` v1 → v2

`parrot.outputs.a2ui.recipes.models.LayoutSpec` moves to v2: catalog
properties live top-level (mirroring the wire `Component` shape) instead of
nested under `properties`, and bindings use `{"path": ...}` instead of
`{"$bind": ..., "optional": ...}` (an optional binding is listed instead in
the layout's own `metadata.extensions.parrot_optional`).
`recipes.SUPPORTED_SCHEMA_VERSION == 2`; a v1 recipe still loads —
`recipes.migrate.migrate_layout(layout, from_version=1)` promotes a single
layout mapping to v2 (it reuses the exact same
`compat.normalize_legacy_component` transform), and
`recipes.migrate.migrate_store(store, dry_run=...)` sweeps an entire
`AbstractRecipeStore`, idempotently re-saving every recipe still below
`SUPPORTED_SCHEMA_VERSION` and returning a `MigrationReport`
(`migrated`/`already_current`/`errors`). A recipe stored above
`SUPPORTED_SCHEMA_VERSION` raises `RecipeSchemaVersionError` rather than
being silently accepted.

### A2A transport constants

| Dialect | v1.0 |
|---|---|
| URI `https://a2ui.org/extensions/a2a/display/v1` | `https://a2ui.org/a2a-extension/a2ui/v1.0` |
| mime `application/vnd.a2ui.envelope+json` | `application/a2ui+json` |

Both are exported from `parrot.a2a.models` as
`A2UI_EXTENSION_URI`/`A2UI_MEDIA_TYPE`.

### Not affected

The public API of `OutputMode.A2UI` and every builder
(`build_surface`/`build_chart`/`build_kpicard`/`build_card`/`build_datatable`/
`build_infographic`) is unchanged — only the wire shape they *emit*
changed. Tool/toolkit call sites do not need to change.
