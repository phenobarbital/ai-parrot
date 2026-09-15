---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: A2UI Linked Surfaces (data-source descriptors instead of baked data)

**Date**: 2026-09-15
**Author**: Jesus Lara (discovery with Claude, same session as the QuerySource `describe-queryslug` brainstorm)
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

Every A2UI surface ai-parrot emits today is **baked**: the agent runs the
data (pandas, `QSourceTool`, a recipe transformer), copies the resulting rows
into `createSurface.dataModel`, and the renderer only *binds* to them. The
surface is a photograph. Refreshing it means either re-running an LLM turn or,
for recipe-backed surfaces, replaying the recipe server-side
(`RecipeRunner`, FEAT-324/326) through `POST /api/v1/ui/surfaces/{id}/refresh`
(FEAT-492). A surface without a `recipe_ref` cannot be refreshed at all
(`UISurfaceRecord.refreshable` is hard-wired to `recipe_name is not None`,
`handlers/models/ui_surfaces.py:83-86`; the handler answers **409**,
`handlers/ui_surfaces.py:590-597`).

Navigator already has the opposite model in production: a **widget** in the
(Vue 2, to be replaced) dashboard is a *structure plus a data reference* —
it POSTs a QuerySource slug with conditions
(`POST /api/v2/services/queries/epson_field_activity` with
`{"firstdate": "2026-08-09", "lastdate": "2026-08-15"}`), post-processes the
rows client-side, and renders a chart, a KPI hero row or a grid. Reloading a
widget is just re-issuing that call. Those widgets are hand-built by people;
nothing lets an agent *produce* one.

The gap this feature closes: an agent that has the `DatasetManager` catalog
of registered slugs and the QuerySource tool can already *replicate* how the
data is obtained. It should be able to emit an A2UI surface that carries
**(1) the component and its presentation props, (2) a data-source descriptor
saying how to fetch the rows, (3) an optional declarative transform, and
(4) optionally the current rows as a snapshot** — so the renderer registers
a fully functional, self-refreshing widget or dashboard, and the same
descriptor lets the server refresh the persisted surface without an LLM.

Who is affected:

- **Navigator users** get agent-authored widgets and dashboards that stay
  live (reload, inline filters, bookmark, share) instead of frozen
  infographics.
- **The `navigator-frontend-next` team** building the new Svelte 5 A2UI
  renderer (`docs/frontend/agentdashboard-a2ui-reference.md`): the
  descriptor is the contract their "widget runtime" executes.
- **Agent authors** (FlexDashboard-style agents, `agents/flex_dashboard.py`)
  who today must bake every number.
- **The ui_surfaces plane** (FEAT-492): persisted surfaces become
  refreshable by descriptor, not only by recipe.

Why now: the QuerySource side of the contract (`describe`, `columns`,
`vocabulary`, keyword fix) is being specified today as
`describe-queryslug` in `../querysource` (target 4.6.0), and the new Svelte
renderer is about to be designed. This document fixes the wire contract
before either ships.

## Constraints & Requirements

Decisions taken during discovery (all with the author, 2026-09-15):

- **Flow:** `feature`, base `dev`.
- **Scope: any surface, not only widgets.** A dashboard may declare several
  sources; its components bind to them by `path`. The mechanism is named
  *linked surface*; `UISurfaceKind` (`dashboard|infographic|widget`) and the
  frontend `inferSurfaceKind` heuristic are unchanged (there is still no
  `kind` on the wire).
- **Where the descriptor lives:** surface-level
  `createSurface.metadata.extensions.parrot_data_sources`, keyed by the
  `dataModel` root key each source fills. Components keep binding with
  ordinary `{"path": "/<key>/rows"}`. Nothing new appears as a top-level
  component prop (spec G4: presentation semantics live in
  `metadata.extensions`, keys `parrot_*`, `a2ui_` reserved —
  `models.py:338-361`).
- **Fetch path: the renderer calls QuerySource directly**
  (`POST /api/v2/services/queries/{slug}`) with the **viewer's JWT**;
  QuerySource PBAC (`slug:execute`, `datasource:use`, `driver:use`) is the
  authorization. ai-parrot-server does not proxy the fetch. The QuerySource
  base URL is renderer configuration, never part of the descriptor.
- **Server-side execution is the alternative lane, not the default:** a
  Python executor runs the same descriptor in-process
  (`QuerySlugSource` → `QS(slug, conditions)`) for `POST .../refresh`
  (FEAT-492) with the **owner's** `PermissionContext`
  (`build_principal_context`, `handlers/ui_surfaces.py:620`), for the HTML
  lane when no snapshot is present, and for scheduled delivery (FEAT-430).
  `UISurfaceRecord.refreshable` becomes `recipe_name is not None or
  has_data_sources`.
- **One descriptor, two executors, one set of golden fixtures.** The DSL is
  implemented in Python (reference) and in TypeScript (renderer); both must
  pass the same JSON in/out fixtures.
- **Transform DSL v1: nine declarative operations, no code.** `select`,
  `rename`, `filter`, `group_by` (with `sum|avg|count|min|max`), `sort`,
  `limit`, `derive` (arithmetic between columns and constants only),
  `pivot`, and `join` (`inner|left`, equality keys, `null` never matches,
  column collisions resolved by prefix, one join per step, between sources
  of the same surface). LLM-generated code is **vetoed** in this version.
- **Library input shapes are the renderer's job, not the DSL's.** Turning
  rows into ECharts pie pairs, gauge values, etc. happens in the renderer's
  adapter (today `a2ui-chart-adapter.ts`), consistent with viz-core's
  "describe what, never how".
- **`transform` inline is the rule; `transform.ref` is supported in v1** as
  a URL to a TypeScript module served by ai-parrot-server from a static,
  anonymously readable route, versioned (`<name>@<version>.js`) and pinned
  by an `integrity` (SRI) hash carried in the descriptor. `ref` transforms
  are catalogued, never LLM-written.
- **Only TOOL-origin builders may emit a descriptor.** A `ProducerOrigin.LLM`
  envelope carrying `parrot_data_sources` fails `validate_envelope` with a
  new code, mirroring D10b (`ACTION_NOT_ALLOWED_FOR_LLM`,
  `catalog/__init__.py:617-632`) and the FEAT-473 inline-data guard
  (`INLINE_DATA_NOT_ALLOWED_FOR_LLM`, `catalog/__init__.py:646-661`). The
  descriptor is assembled by a deterministic builder from the metadata of
  the tool call that actually ran (`QSourceTool` `ToolResult.metadata`:
  `query_slug`, `conditions`, `columns`, `dtypes` — `qsource.py:289-303`;
  or a `DatasetManager` entry with its `permanent_filter`). The LLM chooses
  slug, component and axes; it never types the descriptor.
- **Parameters come from the slug's contract, not from the LLM.**
  `params` are derived from QuerySource `GET /api/v1/queries/{slug}/describe`
  (`derived.variables`: name, canonical `type`, `default`, `required`,
  `accepts_keywords`) via the FEAT-567 `qs_describe` tool. Relative dates
  use QuerySource's keyword vocabulary as condition **values** (`TODAY`,
  `YESTERDAY`, `FDOM`, `LDOM`, `CURRENT_YEAR`, `CURRENT_MONTH`, `LAST_YEAR`;
  `GET /api/v1/queries/vocabulary`), so a "last week" widget stays "last
  week". There is **no** `{today}` placeholder grammar in QuerySource.
- **`locked` conditions are a UX hint only.** A descriptor built from a
  dataset with `permanent_filter` carries those conditions as `locked`
  so the filter bar does not expose them; they are **not** a security
  barrier (a viewer could drop them). Security is QuerySource PBAC plus
  slug design. This must be documented in the wire doc.
- **Snapshot is optional (agent decides).** When present it is the initial
  `dataModel` (with `snapshot_at`); the renderer paints it and then applies
  the refresh policy. Without it the renderer shows a loading state until
  the first fetch, and the server-side lanes (HTML negotiation,
  `bake_envelope`) must execute the descriptor first — `bake_envelope`
  raises `BakeError` on any unresolved binding (`baking.py:140`).
- **Refresh policy:** `on_mount` by default; `manual` and `interval`
  optional. The renderer keeps "Filter" (local, over embedded rows,
  §7.4 of the frontend reference) distinct from "Refresh" (re-fetch with
  the current params).
- **Never leak SQL.** Descriptors reference slugs only; QuerySource raw
  `query` mode is never allowed on the wire.
- **Additive.** No change to existing envelopes, builders' outputs, the
  A2UI models, renderers or the ui_surfaces DDL beyond what is listed in
  Impact. Baked surfaces keep working exactly as today.
- **Dependencies:** QuerySource `describe-queryslug` (FEAT-147 in
  `../querysource`, 4.6.0: `describe`, `columns`, `vocabulary`, UDF keyword
  fix for `date`-typed conditions) and ai-parrot **FEAT-567
  `QuerySourceToolkit`** (`qs_describe`; no artifact exists yet — it must be
  brainstormed and specified before this feature's `/sdd-task`).
- Conventions: Pydantic v2 models, async I/O, `self.logger`, Google
  docstrings, `pytest` + `pytest-asyncio`, golden-file tests
  (`tests/outputs/a2ui/golden/`), conformance registration in
  `tests/outputs/a2ui/conformance/test_all_emitters.py`.

---

## Options Explored

### Option A: Surface-level `parrot_data_sources` extension + TOOL-origin builder + dual DSL executors

Four pieces, all additive:

1. **Descriptor models** (`parrot/outputs/a2ui/linked/models.py`): Pydantic
   `LinkedDataSource` (`kind: "query_slug"`, `slug`, `conditions`,
   `params: {name: {type, default, required, editable, accepts_keywords}}`,
   `locked: [names]`, `transform: TransformSpec | None`, `target` pointer,
   `snapshot_at`, `refresh: {"policy": "on_mount|manual|interval",
   "interval_seconds"}`) and `TransformSpec` (either `ops: [...]` inline or
   `ref: {url, integrity}`), plus the nine `ops` models. JSON Schema is
   exported for the renderer. A surface-level validator (a new loop in
   `validate_envelope`, which today iterates components only) checks the
   extension, the `target` pointers against bindings, and the origin gate
   (`DATA_SOURCES_NOT_ALLOWED_FOR_LLM`).
2. **Deterministic builder** (`builders.build_linked_surface`, plus a
   `surface_metadata` parameter on `build_surface`, which today can only
   attach metadata to the root component, `builders.py:101-107`): takes
   the component descriptor(s), one or more `LinkedDataSource`, and an
   optional snapshot; validates axes/columns against the source's declared
   columns; emits `CreateSurface` with `origin=ProducerOrigin.TOOL` (the
   `build_html_document` precedent, `builders.py:311`). An agent-facing
   toolkit in `parrot_tools` (`LinkedSurfaceToolkit`) wraps it, taking a
   `dataset_name` (DatasetManager) or the metadata of the last
   `QSourceTool` call, and calling FEAT-567 `qs_describe` for `params`.
3. **Python executor** (`parrot/outputs/a2ui/linked/executor.py` +
   `dsl.py`): fetch through `QuerySlugSource.fetch(**conditions)`
   (`sources/query_slug.py:122`), apply the DSL over a `pandas.DataFrame`,
   write into `dataModel[target]`. Wired into `UISurfacesHandler._refresh`
   as a second path next to `RecipeRunner`, and into
   `SurfaceNegotiationService` for the HTML lane when the surface has no
   snapshot. `refreshable` widened. `PublishSurfaceTool` reports
   `refreshable` accordingly.
4. **TypeScript reference executor + renderer lane**: `a2ui-types.ts` gains
   `CreateSurface.metadata`; a `linked/` module (fetch via
   `POST /api/v2/services/queries/{slug}` with the viewer's bearer, DSL
   executor, refresh scheduler, `ref` loader with SRI check) and an
   insertion point in `A2UISurface.svelte` (today a stateless renderer
   with no fetch, `A2UISurface.svelte:12-30`). Shipped in the bundled
   `ai-parrot-server/ui` as the reference implementation and validated
   against the shared golden fixtures; `navigator-frontend-next` ports or
   consumes it (open question on packaging). ai-parrot-server serves
   `ref` transforms from a static route.

✅ **Pros:**
- Matches every discovery decision; no change to the official wire shape
  (surface `metadata.extensions` already exists and validates,
  `models.py:470`, `:341-361`).
- Multiple sources per surface for free; dashboards and widgets use one
  mechanism.
- Baked surfaces, `bake_envelope`, the six satellite renderers and
  `lower()` are untouched: a snapshot makes a linked surface
  indistinguishable from a baked one for them.
- Server-side refresh reuses FEAT-492's route, store and owner-context
  logic; only the executor behind it changes.
- The origin gate keeps the LLM producer path unable to fabricate data
  access, exactly like actions and inline data today.

❌ **Cons:**
- Two executors of the same DSL (Python + TypeScript) must stay in parity;
  the golden fixtures are the contract and they must be maintained.
- Net-new frontend surface: the bundled UI has no API client for
  QuerySource or ui_surfaces at all (`grep` → 0 hits in `ui/src`), so the
  reference lane is written from scratch.
- Viewer-credential fetch means a shared surface (FEAT-492 share token)
  may render the snapshot but fail to refresh for a viewer without
  `slug:execute`; the renderer must degrade gracefully (open question).
- Surface-level validation is a new concept in `validate_envelope`.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` v2 | descriptor + DSL models, JSON Schema export | already the wire model stack |
| `pandas` | Python DSL executor over `QuerySlugSource.fetch()` DataFrames | already a core dependency (DatasetManager) |
| `querysource` (in-process `QS`) | server-side fetch | already used by `QuerySlugSource` (`lazy_import`, `sources/query_slug.py`) |
| `jsonschema` | validate `parrot_data_sources` in the conformance suite | already used by `catalog.validate_message` |
| Svelte 5 + TypeScript | reference renderer lane in `ai-parrot-server/ui` | existing bundled UI stack |
| `aiohttp` static route | serve `ref` transform modules | already the server stack; SRI hash in descriptor |

🔗 **Existing Code to Reuse:**
- `parrot/outputs/a2ui/builders.py:69` `build_surface` (needs `surface_metadata`), `:116` `build_chart`, `:137` `build_kpicard`, `:179` `build_datatable`, `:311` TOOL-origin precedent in `build_html_document`.
- `parrot/outputs/a2ui/catalog/__init__.py:499` `validate_envelope`; `:617-632` D10b gate; `:646-661` inline-data gate; `catalog/base.py:78-86` error codes; `base.py:89-98` `ProducerOrigin`.
- `parrot/outputs/a2ui/models.py:446-470` `CreateSurface` (surface `metadata`), `:338-378` `Extensions`/`SurfaceMetadata`.
- `parrot/outputs/a2ui/baking.py:356` `bake_envelope`, `:187-191` `parrot_optional`, `:140` `BakeError`.
- `parrot/outputs/a2ui/recipes/models.py:69` `DataSourceSpec`, `:90` `TransformStep`, `:51` `RecipeParam`; `recipes/params.py:30-39` `DATE_RESOLVERS`/`resolve_date` (the in-house relative-date precedent, to be superseded by QuerySource keywords for linked sources).
- `parrot/tools/dataset_manager/sources/query_slug.py:36-162` `QuerySlugSource` (`fetch`, `cache_key`, `permanent_filter` wins); `tool.py:966` `add_dataset`; `:60` `DatasetInfo`; `:2766` `list_datasets`.
- `parrot_tools/qsource.py:158-310` `QSourceTool._execute` and its `ToolResult.metadata`.
- `parrot/handlers/ui_surfaces.py:577-645` `_refresh` (owner ctx, `update_envelope`), `:64-95` request models; `handlers/models/ui_surfaces.py:62-86` `UISurfaceRecord.refreshable`.
- `parrot_tools/ui_surfaces.py:60-150` `PublishSurfaceTool`; `bots/mixins/infographic_authoring.py:440` `publish_surface`.
- `parrot/outputs/a2ui/catalog/parrot/filterbar.py:29-129` `FilterBar` (no client state today; `parrot_filter_column` extension).
- `ui/src/lib/components/agents/canvas/a2ui/a2ui-types.ts:63-68` `CreateSurface` (no `metadata`), `a2ui-binding.ts:33-68` pointer resolution, `a2ui-chart-adapter.ts:46-84` `toChartBlockData`, `A2UISurface.svelte:12-30`, `a2ui-kind.ts:29-37`.
- `tests/outputs/a2ui/conformance/test_all_emitters.py:115` `_assert_conformant`; `tests/outputs/a2ui/golden/` byte-equality convention (`test_components_filterbar.py:15-42`).
- `docs/outputs/a2ui-v1.md:140-158` extension key table; `docs/frontend/agentdashboard-a2ui-reference.md:710-818` kinds + client-side filtering contract, `:820-971` renderer design.
- Prior art for a client-executed declarative descriptor with public/private args: `packages/parrot-formdesigner/scripts/gen_frontend_docs.py:78-101` (`x-parrot-rest`).

---

### Option B: A new Parrot catalog component `LinkedWidget` (component-level descriptor)

Add a composite `LinkedWidget{source, child}` to the Parrot catalog. The
descriptor is a top-level prop of that component; it lowers to its child
(Chart/DataTable/KPICard) with the binding pre-resolved from the snapshot.

✅ **Pros:**
- The linked nature is explicit on the wire and per component; a renderer
  dispatches on the component name.
- Fits the existing `register_component` + `lower()` machinery
  (`catalog/__init__.py:111-120`), including `tool_only=True` for the
  origin gate — no new surface-level validation concept.

❌ **Cons:**
- One source per component; a dashboard with two slugs feeding six
  components must repeat or nest descriptors, and shared `join`s have no
  home.
- Puts a data-access descriptor where the official schema expects
  presentation props, contradicting spec G4 (extensions, not top-level
  props) and the "no `kind` on the wire" decision.
- Every satellite renderer needs a `LinkedWidget` degradation path, and
  `lower()` must strip the descriptor for the HTML/PDF lanes.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` v2 | component schema | same as A |

🔗 **Existing Code to Reuse:**
- `parrot/outputs/a2ui/catalog/parrot/chart.py:48-125` component registration + lowering pattern; `catalog/__init__.py:111-120` `register_component(tool_only=...)`.

---

### Option C: Recipes as the descriptor (server-side only)

Reuse `InfographicRecipe` (`DataSourceSpec` + `TransformStep` +
`LayoutSpec`, `recipes/models.py:235-289`): the agent publishes a recipe per
widget, the surface carries a `recipe_ref` (already persisted by FEAT-492),
and *every* refresh is a server-side replay through `RecipeRunner`. The
renderer never fetches.

✅ **Pros:**
- Zero new wire vocabulary and zero frontend data plumbing; FEAT-492
  refresh already works this way.
- Transforms are registered Python functions (`@infographic_transformer`,
  names-not-code, spec G1) — arbitrarily rich and audited.

❌ **Cons:**
- Does not deliver the product goal: the widget is not self-sufficient in
  the browser, every reload is an ai-parrot-server round trip that replays
  pandas, and inline filter changes cannot be local.
- Transformers are Python; the frontend cannot execute them, so
  "viewer-credential fetch" is impossible.
- Recipes are heavyweight for a single KPI card; the agent must publish
  and version a recipe per widget.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| existing `RecipeRunner` | replay | `tools/infographic_recipes/runner.py:243` |

🔗 **Existing Code to Reuse:**
- `parrot/outputs/a2ui/recipes/*`, `tools/infographic_recipes/runner.py:243-274` (`include_envelope`).

---

### Option D (unconventional): Live surfaces pushed over the FEAT-469 SSE leg

Keep the descriptor server-side; the `A2UIRuntime` (`runtime/dispatch.py:76`)
re-fetches on a schedule or on `action` and pushes `updateDataModel`
envelopes over the existing SSE channel (`callRendererFunction` lane,
`/api/v1/agents/{agent_id}/a2ui`). The renderer only applies data-model
updates.

✅ **Pros:**
- No fetch code in the renderer, no DSL parity problem, owner credentials
  always.
- Fits a "live dashboard" story (streaming KPIs) better than polling.

❌ **Cons:**
- Requires a live agent session; a bookmarked or shared surface outside a
  session has nothing to receive from (FEAT-492's motivation).
- Server holds one refresh loop per open surface; scales with viewers, not
  with data.
- Does not replace the Navigator widget model (structure + reference
  executed by the client), which is the stated goal.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| FEAT-469 runtime | SSE push | `runtime/dispatch.py:76-162` |

🔗 **Existing Code to Reuse:**
- `parrot/outputs/a2ui/runtime/` (`A2UIRuntime`, `SurfaceStateStore`), `docs/outputs/a2ui-agent-functions.md`.

---

## Recommendation

**Option A** is recommended because it is the only option that gives the
renderer a self-sufficient widget (fetch with the viewer's credentials,
local transform, refresh without an agent) while leaving every existing
lane untouched: a linked surface with a snapshot is, to `lower()`,
`bake_envelope`, the six renderers and the HTML lane, just a baked surface.
Option B is cheaper on validation but puts data access into presentation
props and cannot express shared sources or joins across a dashboard.
Option C is the current state of the art (FEAT-492 replay) and stays as the
server-side lane inside A; on its own it does not meet the goal. Option D is
worth keeping in mind for streaming KPIs, but it depends on a live session,
which is the exact limitation FEAT-492 removed.

What A trades off, knowingly: a DSL that must be kept in parity across
Python and TypeScript (mitigated by shared golden fixtures and a small,
closed operation set), and a frontend lane that this repo can only ship as
a reference implementation in the bundled UI — the production renderer
lives in `navigator-frontend-next`.

---

## Feature Description

### User-Facing Behavior

**For the agent author / LLM.** Given an agent with a `DatasetManager`
catalog (slugs registered with `add_dataset(query_slug=...)`) and the
FEAT-567 `QuerySourceToolkit`, a request like "make me a weekly field
activity widget" produces:

1. The LLM picks the dataset/slug, runs it once (via the toolkit or
   `dataset_fetch_dataset`) and chooses the component and axes from the
   **real** columns returned.
2. It calls the `build_linked_surface` tool with `dataset_name` (or the
   slug metadata of the last query), the component descriptor and an
   optional `snapshot: true`. The tool calls `qs_describe` for the slug's
   parameter contract, validates axes against columns, marks
   `permanent_filter` keys as `locked`, and emits the envelope with
   `origin=TOOL`.
3. The turn's `a2ui_envelope` is a normal `createSurface`. Example
   (abridged):

```json
{
  "version": "v1.0",
  "createSurface": {
    "surfaceId": "widget-epson-activity-weekly",
    "catalogId": "https://parrot.dev/catalogs/v1",
    "components": [
      {"id": "root", "component": "Chart", "type": "line", "x": "day", "y": ["visits"],
       "title": "Field activity, last 7 days", "data": {"path": "/activity/rows"}}
    ],
    "dataModel": {"activity": {"rows": [{"day": "2026-09-08", "visits": 12}]}},
    "metadata": {"extensions": {
      "parrot_data_sources": {
        "activity": {
          "kind": "query_slug",
          "slug": "epson_field_activity",
          "conditions": {"firstdate": "YESTERDAY", "lastdate": "TODAY", "program": "epson"},
          "params": {
            "firstdate": {"type": "date", "default": "YESTERDAY", "editable": true, "accepts_keywords": true},
            "lastdate":  {"type": "date", "default": "TODAY", "editable": true, "accepts_keywords": true},
            "program":   {"type": "string", "editable": false}
          },
          "locked": ["program"],
          "transform": {"ops": [
            {"op": "group_by", "by": ["day"], "aggregate": {"visits": "sum"}},
            {"op": "sort", "by": [{"column": "day", "direction": "asc"}]}
          ]},
          "target": "/activity/rows",
          "snapshot_at": "2026-09-15T10:00:00Z",
          "refresh": {"policy": "on_mount"}
        }
      }
    }}
  }
}
```

**For the viewer (Svelte renderer).** The surface renders from the snapshot
immediately (or shows a loading state if none). On mount it re-fetches
`POST /api/v2/services/queries/epson_field_activity` with the descriptor's
`conditions` and the viewer's bearer token, runs the transform, writes the
rows to `/activity/rows`, and re-renders. Editable params drive a filter
bar (date pickers accept keywords such as `FDOM`); "Refresh" re-fetches
with the current params; "Filter" stays local over the embedded rows;
"Reload without cache" adds `refresh: true` to the conditions
(QuerySource's own cache bypass). `locked` params are shown read-only.
A fetch denied by QuerySource (404, PBAC) keeps the snapshot on screen with
a non-blocking notice; without a snapshot the widget shows an access
message.

**For persistence (FEAT-492).** "Pin" saves the envelope as today. The
surface is `refreshable` because it has data sources; `POST
/api/v1/ui/surfaces/{id}/refresh` (owner context, share tokens included)
runs the Python executor, updates `dataModel` and `snapshot_at` in place,
and answers negotiated JSON/HTML. `GET ...?format=html` on a surface
without a snapshot executes the descriptor first.

**For a dashboard.** Two slugs → two entries under `parrot_data_sources`
(each with its own params and refresh policy) → KPI cards, charts and a
`DataTable` bound to either; a `join` step in one source's transform may
reference the other source by key.

**`transform.ref`.** `{"ref": {"url": "/static/a2ui/transforms/group_by_day@1.0.0.js",
"integrity": "sha384-…"}}` loads a catalogued module served by
ai-parrot-server (anonymous read); the renderer refuses to execute on
integrity mismatch and falls back to the snapshot.

### Internal Behavior

1. **Models and schema.** `LinkedDataSource`, `TransformSpec`, the nine op
   models and `RefreshPolicy` as Pydantic v2 in
   `parrot/outputs/a2ui/linked/models.py`; `export_json_schema()` writes
   the schema consumed by the TypeScript side and by the conformance suite.
2. **Validation.** `validate_envelope` grows a surface-level pass: parse
   `metadata.extensions.parrot_data_sources` into the models; every
   `target` must be an absolute pointer whose root key exists in
   `dataModel` **or** is referenced by at least one binding; `locked` ⊆
   `params`; `join.with` must name another source of the same surface;
   `kind` ∈ {`query_slug`}; `origin is LLM` → `DATA_SOURCES_NOT_ALLOWED_FOR_LLM`.
   Issues are reported all at once, like today.
3. **Builder.** `build_surface(..., surface_metadata=SurfaceMetadata | None)`;
   `build_linked_surface(components, sources, *, snapshot, surface_id)`
   validates `x`/`y`/`columns` props against each source's declared
   columns (from `describe`/`columns` or the tool metadata), sets
   `origin=ProducerOrigin.TOOL`, and returns `CreateSurface`.
4. **Agent toolkit** (`parrot_tools/linked_surfaces.py`,
   `LinkedSurfaceToolkit(AbstractToolkit)`): `build_linked_surface(...)`
   (LLM-callable) resolves the source from `DatasetManager` (`entry.query_slug`,
   `permanent_filter` → `locked`, `column_types`) or from the last
   `QSourceTool` result; calls FEAT-567 `qs_describe` for `params`; runs
   the Python executor once when `snapshot=True`; returns the envelope in
   the same shape `structured_chart` responses use (`a2ui_envelope` +
   `artifacts[]`, FEAT-473 dual emission).
5. **Python executor** (`linked/executor.py`, `linked/dsl.py`): for each
   source, merge `conditions` with call-time param overrides (locked keys
   cannot be overridden), fetch through `QuerySlugSource(slug).fetch(**conds)`
   under the caller's `PermissionContext` (via `AuthorizingDataSource`
   when a guard is configured), apply the DSL over the DataFrame, write to
   `dataModel[target]` (`orient="records"`), stamp `snapshot_at`. `join`
   pulls the other source's already-executed frame. Pure functions; no LLM.
6. **ui_surfaces integration.** `UISurfaceRecord.refreshable` →
   `recipe_name is not None or _has_data_sources(envelope)`; `_refresh`
   dispatches on which one is present (recipe first when both);
   `SurfaceNegotiationService._respond_html` executes the descriptor when
   the envelope has sources but no snapshot; `PublishSurfaceTool` returns
   `refreshable` from the record.
7. **Static transforms route.** ai-parrot-server serves
   `/static/a2ui/transforms/<name>@<version>.js` from a configured
   directory, anonymous, immutable cache headers; a manifest endpoint
   lists names, versions and integrity hashes for the builder to embed.
8. **Reference renderer lane** (bundled UI): `a2ui-types.ts` adds
   `metadata?: {extensions?: Record<string, unknown>}` to `CreateSurface`;
   `linked/` module = descriptor parsing, `fetchSource()` (QuerySource
   client with bearer from `auth-headers.ts`), `applyTransform()`
   (DSL executor), `RefreshScheduler`, `loadRef()` with SRI; `A2UISurface.svelte`
   becomes stateful over `dataModel` and mounts the lane when
   `parrot_data_sources` is present. Golden fixtures are loaded by the TS
   tests from the Python `golden/linked/` directory.
9. **Docs.** `parrot_data_sources` row in the `docs/outputs/a2ui-v1.md`
   extension table; a new section in the frontend reference (§6.5 linked
   surfaces; §7.4 amended: Filter vs Refresh vs Reload).

### Edge Cases & Error Handling

- **LLM-origin envelope with a descriptor** → `validate_envelope` issue
  `DATA_SOURCES_NOT_ALLOWED_FOR_LLM`; the producer retry loop sees it
  like an action violation.
- **Slug unknown / viewer denied at fetch time** → renderer keeps the
  snapshot and shows a notice; server-side refresh maps `RuntimeError`
  from `QuerySlugSource.fetch` to `502` (data stage) like the recipe path.
- **No snapshot and HTML lane** → executor runs first; on failure the HTML
  lane answers `502` with the same envelope as the refresh path.
- **Locked key overridden in a refresh request** → ignored with a warning
  in the response (`ignored_params`).
- **Transform errors** (missing column, type mismatch in `derive`, join key
  absent) → the executor fails the *source*, not the surface: other sources
  still render; the failed target keeps its snapshot and the error is
  reported in `dataModel["_linked"]["errors"]` (renderer) / response
  `warnings` (server).
- **`ref` integrity mismatch or fetch failure** → transform skipped,
  snapshot shown, error surfaced; never executes unverified code.
- **Interval policy** → minimum interval enforced by the renderer (open
  question); paused when the tab is hidden.
- **Relative-date keywords in a typed `date` param** depend on the
  QuerySource UDF fix shipping in 4.6.0; until then the builder emits
  absolute dates and marks `accepts_keywords: false`.
- **Large results** → the DSL executor works in memory; the builder caps
  a *snapshot* to a configurable row count with `snapshot_truncated: true`
  (the live fetch is not capped; QuerySource `querylimit` may be part of
  `conditions`).
- **Share-token viewers** (FEAT-492) fetch with their own credentials; if
  denied they see the last server-refreshed snapshot, which is why the
  owner-context server refresh stays available.

---

## Capabilities

### New Capabilities
- `a2ui-linked-data-sources`: the `parrot_data_sources` surface extension, its Pydantic/JSON-Schema models, surface-level validation and the TOOL-origin gate.
- `a2ui-transform-dsl`: the nine-operation declarative DSL with Python (reference) and TypeScript executors and shared golden fixtures; `transform.ref` static module serving with SRI.
- `linked-surface-builder`: `build_linked_surface` + `surface_metadata` on `build_surface`; `LinkedSurfaceToolkit` for agents (DatasetManager / QSourceTool metadata → descriptor; `qs_describe` → params).
- `linked-surface-python-executor`: server-side fetch + transform behind FEAT-492 refresh and the HTML lane.
- `a2ui-linked-renderer-lane`: reference Svelte lane in the bundled UI (QuerySource client, refresh scheduler, filter bar from params).

### Modified Capabilities
- `a2ui-surface-rehydration` (FEAT-492, `sdd/specs/a2ui-surface-rehydration.spec.md`): `refreshable` widened; `_refresh` gains the descriptor path; HTML negotiation may execute the descriptor.
- `a2ui-v1-dialect` (FEAT-470): new extension key documented; `validate_envelope` gains a surface-level pass and a new error code.
- `a2ui-v1-structured-outputs` (FEAT-473): linked envelopes emitted with the same dual-emission shape.
- `html-renderer-design-system` (FEAT-493, `FilterBar`): parameter-driven filter bar contract (Filter vs Refresh) — see Open Questions.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/outputs/a2ui/linked/` (`models.py`, `dsl.py`, `executor.py`, `schema.py`) | new | descriptor + DSL models, executors, JSON Schema export |
| `parrot/outputs/a2ui/builders.py` | extends | `surface_metadata` on `build_surface`; `build_linked_surface` |
| `parrot/outputs/a2ui/catalog/__init__.py`, `catalog/base.py` | extends | surface-level validation pass; `DATA_SOURCES_NOT_ALLOWED_FOR_LLM` |
| `parrot/outputs/a2ui/models.py` | none | `CreateSurface.metadata` already exists |
| `parrot/outputs/a2ui/baking.py` | none | snapshot resolves bindings; no-snapshot handled by callers |
| `packages/ai-parrot-tools/src/parrot_tools/linked_surfaces.py` | new | `LinkedSurfaceToolkit` (`build_linked_surface`) |
| `packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py` | modifies | `refreshable` from record instead of `recipe_name is not None` |
| `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py` | modifies | `refreshable` property |
| `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` | extends | descriptor refresh path; HTML lane execution when no snapshot |
| ai-parrot-server static route + manifest for `ref` transforms | new | `/static/a2ui/transforms/<name>@<ver>.js`, anonymous, SRI |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/` (`a2ui-types.ts`, `A2UISurface.svelte`, new `linked/`) | extends / new | reference renderer lane |
| `packages/ai-parrot-server/ui/src/lib/api/` | new | QuerySource client (`services/queries`) with bearer |
| `tests/outputs/a2ui/golden/linked/`, `tests/outputs/a2ui/conformance/test_all_emitters.py` | new / extends | DSL fixtures (shared with TS tests); conformance registration of `build_linked_surface` |
| `docs/outputs/a2ui-v1.md`, `docs/frontend/agentdashboard-a2ui-reference.md` | modifies | extension table; §6.5 linked surfaces; §7.4 Filter/Refresh/Reload |
| FEAT-567 `QuerySourceToolkit.qs_describe` (ai-parrot, not yet written) | depends on | params contract; must be specified before `/sdd-task` here |
| QuerySource `describe-queryslug` (FEAT-147, `../querysource`, 4.6.0) | depends on | `describe`, `columns`, `vocabulary`, UDF keyword fix |
| `navigator-frontend-next` (external) | consumer | production renderer; ports/consumes the reference lane |

No breaking changes. No new Python runtime dependency.

---

## Code Context

### User-Provided Code

```text
# Source: user-provided (conversation, 2026-09-15) — today's Navigator widget data call
POST /api/v2/services/queries/{query_slug}
payload: {"lastdate": "2026-08-15", "firstdate": "2026-08-09"}
# The Vue 2 widget chrome offers: "Clear cache and reload", "Filtering",
# "Temporarily duplicate", "Collapse", "Fullscreen", "Settings", "Help",
# "Screenshot", "Export Data" — a hero row of KPI cards (DSM VISITS, WW EVENTS, ...)
# is one widget fed by one slug.
```

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/outputs/a2ui/builders.py
def build_surface(component: str, properties: dict[str, Any], *, surface_id: str,
                  component_id: str = "root", data_model: dict[str, Any] | None = None,
                  origin: ProducerOrigin = ProducerOrigin.LLM,
                  metadata: ComponentMetadata | None = None) -> CreateSurface:   # L69
    # L101-107: `metadata` goes on the ROOT COMPONENT; CreateSurface.metadata is never set
    # L112: validate_envelope(envelope, origin=origin)
def build_chart(*, chart_type, x, y: Sequence[str], title=None, data_binding: str | None = None,
                show_legend=True, surface_id="chart", data_model=None) -> CreateSurface   # L116
def build_kpicard(*, label, value, unit=None, delta=None, trend=None, surface_id="kpi")  # L137
def build_datatable(*, columns: Sequence[dict], data_binding=None, title=None,
                    total_rows=None, truncated=False, surface_id="table", data_model=None)  # L179
def build_html_document(...)   # L264 — hardcodes origin=ProducerOrigin.TOOL at L311
def build_graph(..., origin: ProducerOrigin = ProducerOrigin.TOOL)   # L316 — only builder exposing origin

# From packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py
def validate_envelope(envelope: CreateSurface | UpdateComponents, *,
                      origin: ProducerOrigin = ProducerOrigin.TOOL,
                      surface_catalog_id: str | None = None) -> None:   # L499
    # per-component loop only; D10b gate L617-632; inline-data gate L646-661; tool_only gate L634-644
def register_component(name, *, requires_actions=False, catalog_id=DEFAULT_CATALOG_ID,
                       is_primitive=False, allowed_parents=None, allowed_children=None,
                       tool_only=False)   # L111-120
# catalog/base.py: ProducerOrigin(str, Enum): TOOL="tool", LLM="llm"   # L89-98
#   ACTION_NOT_ALLOWED_FOR_LLM L78, INLINE_DATA_NOT_ALLOWED_FOR_LLM L82, TOOL_ONLY_NOT_ALLOWED_FOR_LLM L86

# From packages/ai-parrot/src/parrot/outputs/a2ui/models.py
class CreateSurface(A2UIMessageBase):                       # L446, extra="forbid" L463
    surface_id: str = Field(alias="surfaceId")              # L465
    catalog_id: str | None = Field(alias="catalogId")       # L466
    send_data_model: bool = Field(alias="sendDataModel")    # L467
    components: list[Component]                             # L468
    data_model: dict[str, Any] = Field(alias="dataModel")   # L469
    metadata: SurfaceMetadata | None = None                 # L470
class Extensions(RootModel[dict[str, Any]])                 # L341; keys isidentifier(), not "a2ui_" (L351-361)
class ComponentMetadata(BaseModel): extensions: Extensions | None   # L364-373
SurfaceMetadata = ComponentMetadata                          # L378

# From packages/ai-parrot/src/parrot/outputs/a2ui/baking.py
def bake_envelope(envelope: CreateSurface) -> list[dict[str, Any]]   # L356
#   parrot_optional read per component L187-191; unresolved binding → BakeError L140

# From packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py
class RecipeParam: name; default; description                                  # L51
class DataSourceSpec: dataset; alias; sql; conditions; force_refresh=True       # L69
class TransformStep: transformer; inputs; params; output_key                    # L90
# recipes/params.py: DATE_RESOLVERS L30-38; def resolve_date(resolver, *, tz="UTC", now=None) -> str  L39

# From packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py
class QuerySlugSource(DataSource):                                              # L36
    def __init__(self, slug: str, prefetch_schema_enabled: bool = True,
                 permanent_filter: Optional[Dict[str, Any]] = None)             # L51-56
    cache_key -> str   # "qs:{slug}" | "qs:{slug}:f={md5[:8]}"                  # L67-80
    async def fetch(self, **params) -> pd.DataFrame                              # L122; force_refresh→refresh L139-141;
                                                                                 # merged = {**params, **permanent_filter} L143; QS(slug, conditions) L152
# sources/authorizing.py: class AuthorizingDataSource(DataSource) L41;
#   __init__(self, inner, guard, pctx_provider) L58-63; async fetch(**params) L74 (pctx None ⇒ fail-open)

# From packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetInfo(BaseModel): name, alias, description, source_type, source_description,
                              columns: List[str], column_types: Dict[str,str] | None, shape   # L60-90
async def add_dataset(self, name: str, *, description=None, query_slug=None, query=None, table=None,
                      dataframe=None, ..., permanent_filter: dict | None = None, ...) -> str   # L966
async def list_datasets(self) -> List[Dict[str, Any]]                                          # L2766

# From packages/ai-parrot-tools/src/parrot_tools/qsource.py
class QSourceTool(AbstractTool):                                                 # L62
    async def _execute(self, query_slug=None, query=None, conditions=None, additional_filters=None,
                       driver=None, return_format="json", ..., limit=None, **kwargs) -> ToolResult  # L158-169
    # ToolResult.metadata keys: query_slug, raw_query, driver, row_count, return_format, conditions,
    #   + columns, shape, dtypes when return_format == "pandas"                     # L289-303

# From packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py
class UISurfaceRecord(BaseModel): surface_id, kind, title, envelope: dict, catalog_id, agent_id, user_id,
    session_id, recipe_name, recipe_owner, recipe_params, tenant, visibility, allowed_groups, ...   # L62-79
    @property def refreshable(self) -> bool: return self.recipe_name is not None                   # L83-86

# From packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py
class PublishSurfaceRequest(BaseModel)   # L64-89 (kind, title, envelope, source_artifact_id, recipe_*, visibility, allowed_groups)
class RefreshSurfaceRequest(BaseModel): params: dict[str, Any]   # L91-95
async def _refresh(self) -> web.Response:   # L577; 409 when not refreshable L590-597;
    # merged_params = {**record.recipe_params, **req.params} L604;
    # owner_pctx = build_principal_context(record.user_id, channel="ui_surfaces") L620;
    # runner.run(..., include_envelope=True) L622-629; store.update_envelope(...) L638-645
class SurfaceNegotiationService   # L213 (negotiate L221, respond L244, _respond_json L261, _respond_html L270)

# From packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py
async def publish_surface(self, *, kind: str, title: str, envelope: CreateSurface | dict,
                          recipe_name=None, recipe_owner=None, recipe_params=None, overwrite=False,
                          surface_store=None, user_id=None, session_id=None) -> str   # L440
# packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py: class PublishSurfaceTool(AbstractTool) L60;
#   _execute(...) L111-122 returns {"surface_id", "kind", "refreshable": recipe_name is not None} L146-150

# From packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/filterbar.py
FILTERBAR_SCHEMA  # L29-61: {title, filters: [{column, label, options: [{label, value}], multiple?}]}
class FilterBarComponent  # L104; lower() L110 → Row(parrot_variant="filter-bar") of ChoicePicker(parrot_filter_column)
# No client state and no dataModel.filters mapping exist in the component itself.

# From packages/ai-parrot/src/parrot/outputs/a2ui/runtime/
class SurfaceState(BaseModel): surface_id, catalog_id, data_model, updated_at   # runtime/models.py L139-152
class A2UIRuntime  # runtime/dispatch.py L76; __init__(*, executor, surfaces, pending, catalog_id) L88-95
# parrot/tools/abstract.py L78: def current_a2ui_surface_state() -> Optional[Any]
```

```typescript
// From packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-types.ts
interface Binding { path: string }                                        // L14-16
interface WireComponent { id; component; catalogId?; child?; children?; metadata?: { extensions?: Record<string, unknown> }; [prop: string]: unknown }  // L27-40
interface CreateSurface { surfaceId; catalogId?; components: WireComponent[]; dataModel?: Record<string, unknown> }   // L63-68 — NO metadata
interface A2UIEnvelope { version: "v1.0"; createSurface: CreateSurface }   // L72-75
// a2ui-binding.ts: isBinding L13, resolvePointer(path, dataModel) L33, resolveBinding L57, resolveProps L68
// a2ui-chart-adapter.ts: export function toChartBlockData(properties, dataModel): ChartBlockData  L46-49 (labels + series; no pie-pair conversion)
// A2UISurface.svelte: props { envelope } L12; root L14-17; dataModel L18; stateless, no fetch  L26-30
// A2UINode.svelte: resolved = $derived(resolveProps(properties, dataModel)) L35; no FilterBar branch
// a2ui-kind.ts: export function inferSurfaceKind(surface: CreateSurface): SurfaceKind  L29-37
```

#### Verified Imports
```python
from parrot.outputs.a2ui.builders import build_surface, build_chart, build_kpicard, build_datatable   # builders.py
from parrot.outputs.a2ui.catalog import ProducerOrigin, validate_envelope, register_component        # catalog/__init__.py
from parrot.outputs.a2ui.models import CreateSurface, Component, ComponentMetadata, SurfaceMetadata, Extensions   # models.py
from parrot.outputs.a2ui.baking import bake_envelope, persist_envelope, BakeError                    # baking.py:36
from parrot.outputs.a2ui.recipes.models import DataSourceSpec, TransformStep, RecipeParam           # recipes/models.py
from parrot.outputs.a2ui.recipes.params import DATE_RESOLVERS, resolve_date                          # recipes/params.py
from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource                          # sources/query_slug.py:36
from parrot.tools.dataset_manager.sources.authorizing import AuthorizingDataSource                   # sources/authorizing.py:41
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema, current_a2ui_surface_state   # tools/abstract.py
from parrot.auth.permission import build_principal_context                                           # handlers/ui_surfaces.py:29
from parrot_tools.qsource import QSourceTool                                                         # parrot_tools/qsource.py:62
from parrot_tools.ui_surfaces import PublishSurfaceTool                                              # parrot_tools/ui_surfaces.py:60
from parrot.handlers.models.ui_surfaces import UISurfaceRecord, UISurfaceKind                        # ai-parrot-server
```

#### Key Attributes & Constants
- `DEFAULT_CATALOG_ID` → `https://parrot.dev/catalogs/v1` (every public builder sets it).
- `_STRUCTURED_INLINE_DATA_COMPONENTS = {"Chart", "DataTable", "Map"}`, `_STRUCTURED_INLINE_DATA_FIELDS = ("data", "datasets")` (`catalog/__init__.py:105-109`) — the LLM-origin inline-data guard the descriptor gate mirrors.
- `_RESERVED_EXTENSION_PREFIX = "a2ui_"` (`models.py:338`); `parrot_*` keys documented at `docs/outputs/a2ui-v1.md:150-156` (`parrot_role`, `parrot_variant`, `parrot_component_id`, `parrot_optional`, `parrot_unit`, `parrot_trend`, `parrot_series_data`).
- `RecipeRunner.run(name, *, params=None, pctx=None, recipe_owner=None, include_envelope=False) -> RenderedArtifact` (`tools/infographic_recipes/runner.py:243`); `include_envelope=True` ⇒ `artifact.metadata["source_envelope"]` (L271-274); falsy `pctx` ⇒ DatasetManager guards fail **open** (L262-264).
- FEAT-492 refresh precedence: request params > stored `recipe_params` > recipe defaults (`handlers/ui_surfaces.py:604`).
- QuerySource facts (verified in `../querysource`, 2026-09-15): slug endpoint `POST /api/v2/services/queries/{slug}` (`services.py:148-150`); `refresh` popped from conditions to bypass the result cache (`providers/abstract.py:78-82`); keyword vocabulary `UDF_LIST = [CURRENT_YEAR, CURRENT_MONTH, TODAY, YESTERDAY, LAST_YEAR, FDOM, LDOM]` resolved as condition **values** (`rust/src/validators.rs:20-35`, `types/validators.pyx:552-553`); `cond_definition` types (case-insensitive) `literal|int|integer|float|numeric|decimal|epoch|boolean|string|varchar|field|date|datetime|timestamp|uuid|array|json` (`rust/src/validators.rs:280-305`); planned `GET /api/v1/queries/{slug}/describe`, `/{slug}/columns`, `/vocabulary` (`../querysource/sdd/proposals/describe-queryslug.brainstorm.md`).
- Golden convention: `json.dumps(tree.model_dump(mode="json", exclude_none=True), sort_keys=True, indent=2)` byte-equal to `tests/outputs/a2ui/golden/*.json` (`test_components_filterbar.py:15-42`); conformance helper `_assert_conformant(envelope, *, origin=ProducerOrigin.TOOL)` (`conformance/test_all_emitters.py:115`).
- Ledger: `sdd/tasks/.id_ledger.json` → `next_feature_id: 558`, `next_task_id: 3245`.

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot_data_sources`, `LinkedDataSource`, `DataSourceDescriptor`, `LinkedSurface`, `build_linked_surface`, `transform_dsl`~~ — zero hits repo-wide; all net-new (closest prior art: `recipes/models.py` `DataSourceSpec`/`TransformStep`).
- ~~`CreateSurface.metadata` settable through `build_surface`~~ — `builders.py:101-107` only sets root-component metadata; a `surface_metadata` parameter is new.
- ~~A surface-level rule loop in `validate_envelope`~~ — it iterates components only (`catalog/__init__.py:499-682`).
- ~~A QuerySource HTTP client in `packages/`~~ — QuerySource is reached only in-process via `QS(slug=..., conditions=...)`; 0 hits for `services/queries` in Python or in `ui/src`.
- ~~`ui/src/lib/api/a2ui.ts`, `*surfaces*.ts`~~ — the bundled UI has no API client for ui_surfaces or QuerySource (the frontend reference §8.5 describes the external `navigator-frontend-next`).
- ~~`CreateSurface.metadata` in `a2ui-types.ts`~~ — absent (L63-68).
- ~~A `FilterBar` branch in `A2UINode.svelte`~~ — absent; `FilterBar` has no `dataModel.filters` mapping in the catalog component either.
- ~~Pie-pair conversion in `a2ui-chart-adapter.ts`~~ — it emits `labels` + `series` only (L46-84).
- ~~Shared JSON fixtures between Python goldens and `ui/src/**/*.test.ts`~~ — none today.
- ~~FEAT-567 / `QuerySourceToolkit` / `qs_describe`~~ — no brainstorm, spec, task index, branch or worktree in this repo (2026-09-15).
- ~~`{today}` / `{fdom}` placeholder grammar in QuerySource~~ — keywords are condition values, not placeholders.
- ~~`x-parrot-*` descriptors consumed by the A2UI renderer~~ — `x-parrot-rest` exists only in `packages/parrot-formdesigner` (shape precedent, not reusable code).
- ~~`QS.get_definition()`~~ — only `BaseProvider.get_definition()` in QuerySource.

---

## Parallelism Assessment

- **Internal parallelism**: high. Five strands are independent until integration: (1) descriptor + DSL models + JSON Schema + Python DSL executor with golden fixtures; (2) builder + `surface_metadata` + surface-level validation + conformance registration; (3) `LinkedSurfaceToolkit` in `parrot_tools` (blocked on FEAT-567 for `qs_describe`, can stub); (4) ui_surfaces refresh/HTML integration + static `ref` route (server package); (5) reference renderer lane in the bundled UI (TypeScript executor validated against the same fixtures). Docs last.
- **Cross-feature independence**: no in-flight ai-parrot spec touches `outputs/a2ui/linked/` or the builders' surface metadata. Shared files: `handlers/ui_surfaces.py` and `handlers/models/ui_surfaces.py` (FEAT-535 visibility landed; FEAT-492 complete), `catalog/__init__.py` (any concurrent catalog work), `a2ui-types.ts`/`A2UISurface.svelte` (FEAT-527 bundled-UI work, complete). External hard dependencies: QuerySource 4.6.0 (`describe`, `vocabulary`, keyword fix) and FEAT-567.
- **Recommended isolation**: `mixed`.
- **Rationale**: strands 1, 2 and 5 are self-contained modules with their own tests and can run in separate worktrees; strand 4 touches the shared server handler and should be one sequential task; strand 3 must wait for FEAT-567's `qs_describe` contract. The whole feature's `/sdd-task` should not start before FEAT-567 is at least specified and QuerySource's spec is approved.

---

## Open Questions

- [x] Flow type and base branch — *Owner: Jesus Lara*: `feature`, base `dev`.
- [x] Where the descriptor lives — *Owner: Jesus Lara*: surface-level `metadata.extensions.parrot_data_sources`; components bind by `path`; any surface, not only widgets.
- [x] Fetch path for the renderer — *Owner: Jesus Lara*: directly to QuerySource `POST /api/v2/services/queries/{slug}` with the viewer's JWT; no ai-parrot-server proxy. Python executor only for server-side lanes.
- [x] Transform DSL scope — *Owner: Jesus Lara*: nine ops incl. `join` (`inner|left`, equality keys, nulls never match, prefix on collision); no LLM-generated code; library input shapes (pie pairs) belong to the renderer.
- [x] `transform.ref` in v1 — *Owner: Jesus Lara*: yes, URL to a TypeScript module served by ai-parrot-server from a static, anonymously readable route, pinned by an `integrity` (SRI) hash; inline `ops` remains the rule.
- [x] Who may emit a descriptor — *Owner: Jesus Lara*: TOOL-origin builders only; LLM-origin envelopes fail `validate_envelope` (`DATA_SOURCES_NOT_ALLOWED_FOR_LLM`).
- [x] Refresh policy and persisted surfaces — *Owner: Jesus Lara*: `on_mount` default (`manual`/`interval` optional); `refreshable = recipe_name or data_sources`; `POST .../refresh` runs the Python executor with the owner's context.
- [x] `locked` conditions — *Owner: Jesus Lara*: UX hint only; security is QuerySource PBAC + slug design; documented as such.
- [x] Snapshot — *Owner: Jesus Lara*: optional, the agent decides; server-side lanes execute the descriptor when absent.
- [x] Relative dates — *Owner: Jesus Lara*: QuerySource keyword vocabulary as condition values (`TODAY`, `FDOM`, ...), discovered through `describe`/`vocabulary`; no placeholder grammar.
- [ ] Packaging of the TypeScript executor for `navigator-frontend-next`: port the bundled-UI reference module, publish it as an npm package from this repo, or generate it from the JSON Schema + fixtures only? — *Owner: Jesus Lara*
- [ ] FilterBar ↔ params contract: extend the `FilterBar` catalog component with a `parrot_param` binding so one component serves both local filtering (§7.4) and re-fetch params, or introduce a distinct `ParamBar`? — *Owner: Jesus Lara*
- [ ] Minimum `interval` for the `interval` refresh policy and behaviour on hidden tabs (proposal: 30 s minimum, paused when hidden). — *Owner: Jesus Lara*
- [ ] Snapshot row cap when the agent opts in (proposal: 500 rows per source, `snapshot_truncated: true`). — *Owner: Jesus Lara*
- [ ] Share-token viewers (FEAT-492) denied by QuerySource at fetch time: keep the last server-refreshed snapshot silently, show a notice, or trigger a server-side refresh on their behalf (owner context) automatically? — *Owner: Jesus Lara*
- [ ] Multi-tenant slugs (QuerySource FEAT-176 `/api/v1/{tenant}/queries/...`): does the descriptor carry `tenant`, or is it renderer/session context? — *Owner: Jesus Lara*
- [ ] `ref` transform catalogue governance: who publishes modules to the static directory, how versions are retired, and whether the builder may only reference names present in the manifest. — *Owner: Jesus Lara*
- [ ] Does `build_linked_surface` accept a `MultiQuerySlugSource` (several slugs concatenated) as one source, or is that expressed as N sources + `join`/union in the DSL (v1 has no `union` op)? — *Owner: Jesus Lara*
- [ ] Should the HTML lane refuse (`409`) rather than execute the descriptor for surfaces without a snapshot, to keep `GET` side-effect free? — *Owner: Jesus Lara*
- [ ] FEAT-567 sequencing: brainstorm `QuerySourceToolkit` (with `qs_describe`, `qs_columns`, `qs_vocabulary`, `qs_run`) right after the QuerySource spec is approved, before this feature's `/sdd-spec`? — *Owner: Jesus Lara*
