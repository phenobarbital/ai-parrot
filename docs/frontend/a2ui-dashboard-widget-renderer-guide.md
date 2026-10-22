# A2UI Dashboard + Widget Renderer — Frontend Build Guide

**Audience**: a frontend team building a **single** Svelte 5 renderer (TypeScript, shadcn-svelte / bits-ui,
Tailwind v4) that draws every A2UI surface ai-parrot emits — static, linked, and dashboard-based — with the
right refresh / reload / filter controls for each.
**Verified against**: `ai-parrot` branch `dev` at `35ea61fb3` (2026-10-08). Paths are relative to the repo
root; core source is `packages/ai-parrot/src/parrot/`, server handlers `packages/ai-parrot-server/src/parrot/`,
the bundled admin UI `packages/ai-parrot-server/ui/`.
**Companion documents** (this guide does not repeat them):

| Document | What it owns |
|---|---|
| `docs/frontend/agentdashboard-a2ui-reference.md` | Full A2UI v1.0 wire format, every catalog component's props, chat/RPC/persistence API tables, TS wire types (§9) |
| `docs/outputs/a2ui-linked-surfaces.md` | Normative linked-surface wire (`parrot_data_sources`), refresh semantics, trust model |
| `docs/tools/querysource-toolkit.md` | The agent-side tools that *produce* linked surfaces (`qs_build_linked_surface`, `qs_build_linked_dashboard`) |
| `docs/outputs/infographic-recipes.md` | Recipes: the deterministic server-side replay that backs static dashboards |

Status legend used throughout: **EXISTS** (implemented on `dev`, with file refs) · **SPECIFIED** (in a spec/doc, not
yet in code) · **APPROVED** (decision taken with the product owner on 2026-10-08; build it as written) ·
**PROPOSED** (this guide's recommendation; needs sign-off before anyone implements it).

---

## 0. The one-paragraph model

Every surface is one A2UI `createSurface` message: a flat list of components (adjacency by `id`), a `dataModel`
(JSON), and bindings `{"path": "/pointer"}` from component props into that data model. **What differs between
the three surface types is only where the rows in `dataModel` come from and who may recompute them**:

| Type | Rows come from | Recompute action | Who owns the button |
|---|---|---|---|
| **Static** (baked) | embedded in `dataModel` at emit time | **Reload**: ask the server to re-run the recipe (`POST …/refresh`) or re-ask the agent | the surface (one "Reload" for the whole infographic) |
| **Linked** | the renderer fetches each `query_slug` descriptor from QuerySource with the viewer's token | **Refresh**: re-fetch that source (`refreshSource(key)`); **Reload**: change a param (`setParam`) | the widget (one per source) + optional collapsible filters |
| **Dashboard-based** | the *dashboard* owns N sources fetched once; widgets bind to a source key or to a `derived` view of it | **Refresh**: `refreshAll()` re-fetches the dashboard's sources and recomputes every derived view | the dashboard (widgets have no fetch of their own) |

The descriptor that makes a surface linked or dashboard-based is one extension key on the surface:
`metadata.extensions.parrot_data_sources` (EXISTS, `parrot/outputs/a2ui/linked/models.py:284`). A surface
without that key is static. A surface whose sources are all read by several widgets (or through `derived`
views) is a dashboard. **There is no third wire shape**: the renderer is one code path with a per-source
"origin" switch (§5).

---

## 1. Decisions recorded in this guide

These map the requirements in the original brief onto what the codebase already has. Each is a decision the
frontend can rely on. D2, D3, D7, D8 were approved and D9 confirmed on 2026-10-08.

| # | Requirement (brief) | Decision | Status |
|---|---|---|---|
| D1 | "The dashboard owns a dataset configuration fetched once; each widget is associated to one of the N slugs" | Already the **linked dashboard** shape: `parrot_data_sources` on the dashboard envelope, widgets bind `/<key>/rows` or declare `kind: "derived"` from a key. One fetch per key per pass. | EXISTS (`docs/outputs/a2ui-linked-surfaces.md` §2b, `examples/a2ui/dashboard.py`) |
| D2 | "The dashboard, not the widgets, has the refresh button" | A widget bound to a dashboard source (origin `shared` or `derived`, §5.1) renders **no** refresh control at all. The dashboard frame renders **Refresh all** (`refreshAll()`) and, when persisted, **Server refresh** (`POST …/refresh`). | **APPROVED 2026-10-08.** Buttons EXIST in the admin UI lane (`A2UISurface.svelte:256-259`); hiding them on dashboard-bound widgets is the rule for the new renderer (the admin lane still shows one per source key) |
| D3 | "Widgets of a linked surface each have their own refresh and, as a collapsible, their filter conditions" | A widget with its **own** `query_slug` source (origin `source`) renders its refresh button and a collapsible `ParamPanel` built from `params` / `locked` (§6.3) — on a linked surface **and** inside a dashboard, because its source is not the dashboard's. | **APPROVED 2026-10-08.** Fetch/refresh EXISTS; the per-widget frame with collapsible params is new UI to build |
| D4 | "Static widgets / infographics have a Reload that calls the a2ui surface backend to recompute" | Reload = `POST /api/v1/ui/surfaces/{id}/refresh {"params": {...}}` when the surface is persisted and `refreshable` (recipe-backed). Non-persisted static surfaces get **no** Reload button: nothing on the server can recompute them (§4.1). | EXISTS |
| D5 | "A2UI supports transformation recipes the renderer must call on the backend" | Two distinct server-side things exist and must not be confused: (a) **infographic recipes** — the whole static dashboard is recomputed by `…/refresh`; (b) **python transformers on a linked source** (`transform.python`) — the renderer fetches that one source through `POST …/sources/{key}/data` instead of QuerySource. The renderer never names a transformer; it only calls the endpoint. | EXISTS (FEAT-636) |
| D6 | "The renderer should have local transformations (lodash-like) to turn tabular data into what the chart library needs" | Two layers, deliberately separate: **(a) the wire transform DSL** (ten ops, deterministic, Python ↔ TS parity-tested) runs *what the envelope declares*; **(b) adapters** (`rows → ECharts option`, `rows → grid columns`) are renderer-private and never declared on the wire. Do **not** add lodash for (a) — parity with Python is the contract. | (a) EXISTS (`ui/.../linked/dsl.ts`); (b) EXISTS for Chart (`a2ui-chart-adapter.ts`), extend per component |
| D7 | "One renderer for the three types" | One `A2UISurface` with a `LinkedLane` that is created only when `parrot_data_sources` is present; every widget goes through the same `WidgetFrame` whose controls are chosen by the per-widget `origin` (§5). | **APPROVED 2026-10-08** (implied by D2/D3); structure built from EXISTING pieces |
| D8 | "Iterate over all A2UI widget types and build a widget-like box for each" | §7 lists every component of the three catalogs with its data-bearing field, whether it can be linked, and which frame controls it gets. | Catalog EXISTS; frame mapping **APPROVED 2026-10-08** |
| D9 | "A widget surface that points at a dashboard with associated datasets (dashboard source)" | **Covered by D1**: the widget lives inside the dashboard envelope and binds a dashboard source (`shared`) or a `derived` view of it. A widget in a *separate* surface referencing *another* surface's dataset is a different thing: not supported, ruled out by the decision of record (reference §7.4 item 7); §9 keeps a sketch only in case the product ever needs it. | **CONFIRMED 2026-10-08**: the in-envelope shape is what was meant; the cross-surface variant stays ABSENT |

---

## 2. Backend actors and URLs the renderer talks to

### 2.1 Authentication

All ai-parrot routes below need an authenticated user: the Navigator auth middleware accepts the **session
cookie** or `Authorization: Bearer <token>` (EXISTS, `handlers/ui_surfaces.py:324-326` via
`@is_authenticated()` + `@user_session()`). QuerySource routes accept the **same bearer** (the admin lane reads
it from `localStorage` key `ai_parrot_token`, `ui/src/lib/api/auth-headers.ts:16-20`). Unauthenticated →
`401` with an empty JSON body. Use native `fetch` for QuerySource and for the surfaces data endpoints, **not**
an axios instance whose 401 interceptor logs the user out (`ui/src/lib/api/querysource.ts:1-5`).

### 2.2 URL map

| # | Purpose | Method + path | Handler | Status |
|---|---|---|---|---|
| U1 | Ask an agent for a surface (chat turn) | `POST /api/v1/agents/chat/{agent_id}` body `{"query", "session_id", "output_mode": "a2ui"}` → `{"a2ui_envelope": {…} \| [{…}], "output", "metadata": {"a2ui_surface_id"?}}` | `AgentTalk.post` (`handlers/agent.py`) | EXISTS |
| U2 | List persisted surfaces | `GET /api/v1/ui/surfaces[?kind=dashboard\|infographic\|widget]` → `{"status","count","surfaces":[SurfaceMetadata]}` | `UISurfacesHandler._get_list` (`handlers/ui_surfaces.py:479`) | EXISTS |
| U3 | Open a persisted surface | `GET /api/v1/ui/surfaces/{surface_id}[?share=token][&format=json\|html]` → `{"status","envelope": CreateSurface,"metadata"}` | `_get_one` (`:470`) | EXISTS |
| U4 | Pin / persist a surface | `POST /api/v1/ui/surfaces` body `PublishSurfaceRequest` → `201 {"surface_id"}` | `_pin_save` (`:521`) | EXISTS |
| U5 | **Reload / Refresh on the server** (recipe replay or descriptor re-fetch under the owner's identity) | `POST /api/v1/ui/surfaces/{surface_id}/refresh[?share=token]` body `{"params": {…}}` → the refreshed surface (JSON or HTML by negotiation); header `X-Parrot-Refresh-Warnings: ["…"]` possible | `_refresh` (`:630`) → `_refresh_linked` (`:701`) for linked | EXISTS |
| U6 | **Fetch one python-transformed source** | `POST /api/v1/ui/surfaces/{surface_id}/sources/{key}/data[?share=token]` body `{"params": {…}}` → `{"status","key","rows","truncated","snapshot_at","warnings"}` | `_source_data` (`:749`) | EXISTS |
| U7 | Share / revoke / visibility / delete | `POST …/share`, `DELETE …/share/{token}`, `PATCH …/{surface_id}`, `DELETE …/{surface_id}` | `ui_surfaces.py` | EXISTS (see reference §3.4) |
| U8 | **Fetch a query-slug source directly** (linked lane) | `POST /api/v2/services/queries/{slug}` (default) · `POST /api/v1/{tenant}/queries/{slug}` (when `tenant` set) · `POST /api/v3/queries/{slug}` (only `is_multiquery`) — body = QuerySource conditions (§3) → JSON rows, or **`204` + `x-status: Empty Result`** for zero rows | QuerySource (navigator), **not** ai-parrot-server; base URL `PUBLIC_QUERYSOURCE_URL`, defaults to the API origin | EXISTS (`ui/src/lib/api/querysource.ts:29-37`) |
| U9 | Published renderer transform modules (`transform.ref`) | `GET {apiBase}/static/a2ui/transforms/manifest.json` and `…/<name>@<semver>.js` (anonymous static; SRI-verified by the client) | `handlers/a2ui_transforms.py:44` writes them | EXISTS |
| U10 | Renderer → agent RPC (actions, agent functions, SSE) | `POST /api/v1/agents/{agent_id}/a2ui?session_id=…`, `GET …/a2ui` (SSE), `GET …/a2ui/capabilities`, `GET …/a2ui/surfaces/{surface_id}` | `A2UIHandler` (`handlers/a2ui.py`) | EXISTS |
| U11 | Infographic recipes CRUD/run | `GET/PUT/DELETE /api/v1/infographic_recipes[/{name}]`, `POST …/{name}/run` | `RecipeHandler` (`handlers/infographic_recipes.py`) | EXISTS — the renderer should **not** call `/run` (returns artifact metadata, not a surface); use U5 |

**There is no ai-parrot-server route that executes a bare query slug and returns rows.** Slug rows reach the
browser either directly from QuerySource (U8) or, for python-transformed sources, through U6. This is by design
(`docs/outputs/a2ui-linked-surfaces.md` §3: "ai-parrot-server never proxies").

### 2.3 Persistence model the frontend sees

`navigator.ui_surfaces` (EXISTS, `handlers/models/ui_surfaces.py:110`): `surface_id` (uuid4, **differs** from the
envelope's `surfaceId`), `kind`, `title`, `envelope` (JSONB — the whole `createSurface`, including
`parrot_data_sources` and its snapshots), `agent_id`, `user_id`, `session_id`, `recipe_name`, `recipe_params`,
`tenant`, `visibility`, `allowed_groups`, timestamps. `metadata.refreshable` is `true` when the surface has a
`recipe_name` **or** has `parrot_data_sources` (`UISurfaceRecord.refreshable`). Key your UI state on the stored
`surface_id`; keep the envelope `surfaceId` for RPC messages.

---

## 3. The QuerySource conditions dialect (what the renderer POSTs)

The body of every U8 request is a **flat dict of conditions**. QuerySource parses it in three passes (verified
against querysource 5.1.2; `parrot_tools/querysource/dialect.py` is the authoritative reference):

1. **Option keys are popped first.** These never become SQL columns:

   | Key | Type | Meaning |
   |---|---|---|
   | `fields` | `string[]` | columns to project (overrides the slug's stored fields); SQL expressions are allowed, e.g. `"count(*) as total"` |
   | `querylimit` (alias `_limit`) | int | row limit — **the lane always sets this**, capped at 5000 |
   | `_offset`, `paged`, `page` | int / bool / int | row offset or page-based pagination |
   | `ordering` (alias `order_by`) | `string[]` | `ORDER BY`, e.g. `["qty DESC"]` — **not** `["-qty"]` |
   | `grouping` (alias `group_by`) | `string[]` | `GROUP BY` columns |
   | `filter` (alias `where_cond`) | object | ad-hoc WHERE clauses in the grammar below |
   | `refresh` | bool | bypass the QuerySource cache — **send only `true`, never `false`** (omit otherwise) |
   | `distinct`, `add_fields`, `filter_options`, `qry_options`, `hierarchy` | | rarely used by renderers |
   | `conditions` | object | nested placeholder values; merged over the flat ones |

2. **Remaining keys that match a declared placeholder** of the slug (`cond_definition`, e.g. `{firstdate}` in its
   SQL) become **placeholder substitutions**. Merge order: stored defaults < flat keys < nested `conditions`.
3. **Any other key becomes a WHERE filter** — so a typo in a placeholder name silently turns into `col = 'v'`.
   The toolkit validates this on the agent side; the renderer only ever re-sends what the descriptor declared.

**WHERE grammar** (`filter` values):

| JSON | SQL |
|---|---|
| `"col": "v"` | `col = 'v'` |
| `"col": "!v"` or `"col!": "v"` | `col != 'v'` |
| `"col": ["a","b"]` · `"col!": [...]` | `col IN (...)` · `NOT IN` |
| `"col": [">=", 10]` | `col >= 10` (first item ∈ `< > >= <= <> != IS NOT IS`) |
| `"col": {">": 10}` | `col > 10` (single key ∈ `>= <= <> != < >`) |
| `"col": {"@>": [{"course": "X"}]}` | `col @> '[...]'::jsonb` (JSONB ops `@> <@ @>\| -> ->>`, querysource ≥ 5.1) |
| `"col": "BETWEEN 1 AND 5"` | `(col BETWEEN 1 AND 5)` — no `;`, `--`, `/*`, `UNION`, `SELECT` |
| `"col": "null"` / `"!null"` | `IS NULL` / `IS NOT NULL` |
| `"col": true` | `col = True` |

Keys must be identifier-safe (`[A-Za-z0-9_.]` after stripping suffix chars `|!~#@:`); unsafe keys are silently
dropped by QuerySource. Values starting with `@` (deployment variables like `@today`) are **rejected on the linked
wire**; relative dates use the UDF keywords `TODAY, YESTERDAY, FDOM, LDOM, CURRENT_YEAR, CURRENT_MONTH, LAST_YEAR`
(`dialect.py::reject_variable_values`).

**How a descriptor becomes a body** (EXISTS, TS twin `linked/conditions.ts`, parity-pinned by
`linked/contract/fixtures/conditions/*.json`):

```ts
// 1. request.placeholders in order, then locked values (locked wins on the same name)
// 2. request.filter verbatim          → body.filter
// 3. fields / ordering / grouping     → only when non-empty
// 4. request.offset                   → body._offset only when truthy; never `limit`
const body = { ...deriveConditions(src.request, lockedValues), querylimit: Math.min(src.request.limit ?? 5000, 5000) };
if (manualRefresh) body.refresh = true;
```

**Response shape**: a JSON array of row objects (`orient="records"`) **or**, for MultiQuery slugs, an object of
named frames. `selectFrame` (`linked/fetch.ts:27`) picks `src.multi_output`, else `result`, else the sole frame,
else throws `FrameSelectionError`. A `204` is zero rows. A `404` is rendered as **"unavailable"**, never "denied"
(no existence oracle).

**Worked example** — the Polestar dashboard's `kpis` source (`examples/a2ui/dashboard.py`):

```json
POST /api/v2/services/queries/polestar_graduates_directory
{
  "fields": [
    "count(*) as total",
    "count(*) FILTER (WHERE graduation_details @> '[{\"course\": \"Pilates Studio\"}]') as studio",
    "count(*) FILTER (WHERE jsonb_array_length(graduation_details) > 1) AS multi_graduates"
  ],
  "querylimit": 5000
}
→ 200 [{"total": 17572, "studio": 9191, "multi_graduates": 2884}]
```

---

## 4. The three surface types on the wire

### 4.1 Static (baked) surface

```jsonc
{"version": "v1.0", "createSurface": {
  "surfaceId": "flex-program-dashboard-infographic",
  "catalogId": "https://parrot.dev/catalogs/v1",
  "components": [
    {"id": "root", "component": "Infographic", "title": "Flex Program Dashboard",
     "sections": [{"heading": "Hero", "components": [
        {"component": "KPICard", "properties": {"label": "Worked Hours", "value": {"path": "/payroll_hero/worked_hours_total"}}}]}]}
  ],
  "dataModel": {"payroll_hero": {"worked_hours_total": 18234.5}}
  // no metadata.extensions.parrot_data_sources
}}
```

- **Rows**: everything is in `dataModel`. Nothing is fetched on mount.
- **Reload**: only when the surface is persisted **and** `metadata.refreshable` is true (recipe-backed). Call
  U5 with the current params; the response **is** the new surface — replace components and data model
  wholesale. `409 {"refreshable": false}` means no recipe: hide the button. `422`/`502` carry a
  `RecipeRunError` (`stage`, `transformer`, `dataset`, `missing_columns`, `detail`) — show `detail`, keep the old
  rows.
- **Filter**: FilterBar filters locally over the embedded rows (reference §7.4). No fetch.
- **Non-persisted static widgets** (a `structured_chart` turn in chat): no Reload. The only way to recompute is
  another chat turn. Offer **Pin** (U4) to make the surface durable; auto-pin dashboards.

### 4.2 Linked surface (one widget, one source)

```jsonc
{"createSurface": {
  "surfaceId": "qs-epson_field_activity-…",
  "components": [
    {"id": "filters", "component": "FilterBar", "filters": [
       {"column": "store_id", "label": "Store", "multiple": true, "options": [...],
        "param": {"source": "rows", "name": "store_id"}}]},          // ← parrot_param after lowering
    {"id": "root", "component": "Chart", "type": "line", "x": "visit_date", "y": ["visits"], "data": {"path": "/rows/rows"}}
  ],
  "dataModel": {"rows": {"rows": []}},                                 // definition-only: empty until mount
  "metadata": {"extensions": {"parrot_data_sources": {
    "rows": {
      "kind": "query_slug",
      "slug": "epson_field_activity", "tenant": null, "is_multiquery": false,
      "request": {"placeholders": {"firstdate": "FDOM", "lastdate": "TODAY"}, "filter": {}, "fields": [], "ordering": [], "grouping": [], "limit": 2000},
      "conditions": {"firstdate": "FDOM", "lastdate": "TODAY"},     // derived cache of request, for renderers without a lane
      "params": {"firstdate": {"type": "date", "default": "FDOM", "editable": true, "accepts_keywords": true},
                 "lastdate":  {"type": "date", "default": "TODAY", "editable": true, "accepts_keywords": true},
                 "store_id":  {"type": "str", "editable": true}},
      "locked": [],
      "refresh": {"policy": "on_mount"},
      "transform": null,
      "target": "/rows",
      "snapshot_at": null, "snapshot_truncated": false
    }}}}
}}
```

Invariants (EXISTS, `linked/models.py`): the source **key** equals the first token of `target`; rows always
land as `dataModel[key] = {"rows": [...]}` — the whole value is replaced, never merged
(`A2UISurface.svelte:150-153`); `locked` names must exist in `params`; `refresh.interval_seconds ≥ 30`.

- **Mount**: `RefreshScheduler` runs the policy (`on_mount` fetch once; `manual` never auto-fetches; `interval`
  re-fetches while the tab is visible, paused when hidden).
- **Refresh (widget button)**: `refreshSource(key)` → U8 with `refresh: true`, then every dependent source
  (join/union/derived) in dependency order. Concurrent calls share one in-flight promise.
- **Reload via a param**: a FilterBar filter carrying `parrot_param: {source, name}` calls
  `setParam(source, name, value)` which re-fetches **that** source with the new placeholder; locked or undeclared
  names are ignored. Filters without `parrot_param` filter locally.
- **Transform on the source**: `transform.ops` (DSL, runs in the renderer after fetch), `transform.ref`
  (SRI-pinned module loaded from U9; falls back to the snapshot when the module fails verification), or
  `transform.python` (**the renderer does not fetch QuerySource**: it calls U6 and the rows come back final;
  only possible when the surface is persisted — otherwise show the snapshot with "saved data").
- **Persisted + Server refresh**: U5 with `{"params": currentParams}` re-fetches every source under the
  **owner's** identity and persists a fresh snapshot (≤ 500 rows per source). Surface `409 "stale refresh"` as
  "someone else refreshed this; reloading" and re-GET the surface.
- **Share-token viewers**: show the snapshot and "data as of `snapshot_at`"; the only live action is U5/U6
  (server side, owner identity). Never call U8 for them.

### 4.3 Dashboard-based surface (dashboard-owned sources)

```jsonc
{"createSurface": {
  "surfaceId": "polestar-graduates-dashboard",
  "components": [
    {"id": "root", "component": "Column", "children": ["kpi-row", "charts-row", "grid"]},
    {"id": "kpi-row", "component": "Row", "children": ["kpi_total", "kpi_studio"]},
    {"id": "kpi_total",  "component": "KPICard", "label": "Graduates", "value": {"path": "/kpis/rows/0/total"}},
    {"id": "kpi_studio", "component": "KPICard", "label": "Studio",    "value": {"path": "/kpis/rows/0/studio"}},
    {"id": "charts-row", "component": "Row", "children": ["by_country", "by_course"]},
    {"id": "by_country", "component": "Chart", "type": "bar", "x": "country", "y": ["graduates"], "data": {"path": "/by_country/rows"}},
    {"id": "by_course",  "component": "Chart", "type": "pie", "x": "course",  "y": ["graduates"], "data": {"path": "/by_course/rows"}},
    {"id": "grid", "component": "DataTable", "columns": [{"name": "full_name"}, {"name": "country"}], "data": {"path": "/graduates/rows"}}
  ],
  "dataModel": {"kpis": {"rows": []}, "geo": {"rows": []}, "by_country": {"rows": []}, "by_course": {"rows": []}, "graduates": {"rows": []}},
  "metadata": {"extensions": {"parrot_data_sources": {
    "kpis":       {"kind": "query_slug", "slug": "polestar_graduates_directory", "request": {"fields": ["count(*) as total", "…"]}, "target": "/kpis", "…": "…"},
    "geo":        {"kind": "query_slug", "slug": "polestar_graduates_directory", "request": {"fields": ["country","licensee","count(*) as graduates"], "grouping": ["country","licensee"]}, "target": "/geo", "…": "…"},
    "by_country": {"kind": "derived", "from": "geo", "target": "/by_country",
                   "transform": {"ops": [{"op": "group_by", "by": ["country"], "aggregate": {"graduates": "sum"}},
                                         {"op": "sort", "by": [{"column": "graduates", "direction": "desc"}]}]}},
    "by_course":  {"kind": "query_slug", "slug": "polestar_graduates_by_course", "target": "/by_course", "…": "…"},
    "graduates":  {"kind": "query_slug", "slug": "polestar_graduates_directory", "request": {"fields": ["full_name","country"], "ordering": ["student_uid"], "limit": 500}, "target": "/graduates", "…": "…"}
  }}}
}}
```

This is the `qs_build_linked_dashboard` output (EXISTS, FEAT-610). Three widget origins coexist in one envelope:

| Widget | Origin | Fetches? | Refresh control |
|---|---|---|---|
| `kpi_total`, `kpi_studio` | **dashboard source** `kpis` (bound directly to `/kpis/rows/0/<col>`) | no — `kpis` is fetched once for both | none on the widget; **Refresh all** on the dashboard |
| `by_country` | **derived view** of `geo` (DSL `group_by` in the renderer) | never — recomputed when `geo` changes | none; refreshing it means refreshing `geo`, which the dashboard does |
| `by_course`, `graduates` | **own `query_slug` source** (FEAT-610 one-widget-one-source) | yes, independently | per-widget `Refresh` + collapsible params (D3); **Refresh all** also re-fetches them |

Refresh matrix (normative, `docs/outputs/a2ui-linked-surfaces.md` §2b): **Refresh all** re-fetches every
`query_slug` source sequentially in dependency order and recomputes derived views; refreshing one shared key
cascades to its dependents; a parent failure marks its derived views `error` and keeps the snapshot; `setParam`
on a derived key is ignored with a warning. A derived view aggregates **what its parent fetched** (≤ 5000 rows):
when the full set is bigger, the aggregation belongs in the parent's `request.grouping`, and a server-paged
grid can never feed a derived view.

---

## 5. One renderer, one origin switch

### 5.1 Resolving a widget's data origin

For every component whose catalog definition has data-bearing fields (§7), the renderer resolves **one** of
four origins at mount time, from the first token of its binding pointer:

```ts
type Origin =
  | { kind: 'inline' }                                     // no descriptor for that root key → static rows
  | { kind: 'source'; key: string }                         // key is a query_slug descriptor
  | { kind: 'derived'; key: string; from: string }          // key is a derived descriptor
  | { kind: 'shared'; key: string };                        // key is a query_slug descriptor ALSO read by ≥2 widgets

function originOf(component: WireComponent, sources: LinkedSources | null, readers: Map<string, number>): Origin {
  const ptr = bindingPointer(component);                    // e.g. "/kpis/rows/0/total" → "kpis"
  if (!ptr || !sources) return { kind: 'inline' };
  const key = ptr.split('/')[1]?.replace(/~1/g, '/').replace(/~0/g, '~');
  const src = key ? sources[key] : undefined;
  if (!src) return { kind: 'inline' };
  if (isDerived(src)) return { kind: 'derived', key, from: src.from };
  return (readers.get(key) ?? 0) > 1 ? { kind: 'shared', key } : { kind: 'source', key };
}
```

`readers` is computed once per surface by walking every component's bindings (`bindingPointer` returns the
`data` / `value` / `delta` / `layers[i].data` pointer per component type, see §7). `kind` discriminator rule
(EXISTS, `linked/types.ts::isQuerySlug`): a descriptor without `kind` is `query_slug`; one with `from` is
`derived`.

### 5.2 Surface-level mode

```ts
type SurfaceMode = 'static' | 'linked' | 'dashboard';
function surfaceMode(surface: CreateSurface, origins: Origin[]): SurfaceMode {
  const sources = getDataSources(surface);                  // null → static  (linked/types.ts:63)
  if (!sources) return 'static';
  const shared = origins.some(o => o.kind === 'shared' || o.kind === 'derived');
  return shared ? 'dashboard' : 'linked';
}
```

A surface persisted with `kind: "dashboard"` (U3 `metadata.kind`) is authoritative over the heuristic.

### 5.3 Control matrix (what each frame renders)

| | `static` surface | `linked` surface | `dashboard` surface |
|---|---|---|---|
| **Surface toolbar** | `Reload` (only if persisted + `refreshable`) · `Pin` (if not persisted) · `Open HTML` | `Refresh all` · `Server refresh` (if persisted) · `Pin` | `Refresh all` · `Server refresh` (if persisted) · `Pin` · dashboard `ParamPanel` (union of all unlocked params, grouped by source) |
| **Widget with origin `inline`** | title only | title only | title only |
| **Widget with origin `source`** | — | `Refresh` + collapsible `ParamPanel` (its `params`) + status line (D3) | same as linked: `Refresh` + collapsible `ParamPanel` + status line (D3) — its source is its own, not the dashboard's; its params are **also** listed in the dashboard panel |
| **Widget with origin `shared` / `derived`** | — | — | **no refresh control, no panel** (D2); status line mirrors its source key |
| **Status line** | — | `loading` · `ready` (as of …) · `snapshot` ("saved data, save to refresh live") · `unavailable` · `error` | same, per source key; the dashboard toolbar shows the oldest `snapshot_at` |

The five `SourceStatus` values are EXISTING (`linked/index.ts:42`); the status wording is the admin lane's
(`A2UISurface.svelte:230-247`) and should be kept so both UIs say the same thing.

### 5.4 Data flow

```
                     ┌────────────── A2UISurface (one per envelope) ──────────────┐
 envelope ──────────►│ index components by id · seed dataModel · compute origins  │
                     │ mode = static | linked | dashboard                         │
                     │                                                            │
                     │  if parrot_data_sources:  LinkedLane (createLinkedLane)    │
                     │     ├─ RefreshScheduler per query_slug source              │
                     │     ├─ deriveConditions → fetchSource (U8)  ─┐             │
                     │     ├─ transform.python → fetchSourceData (U6)│ rows        │
                     │     ├─ transform.ops  → dsl.applyTransform   │             │
                     │     ├─ transform.ref  → loadRef (U9, SRI)    │             │
                     │     └─ derived keys   → recompute from parent frame        │
                     │           onUpdate(key, rows, status) ──► dataModel[key] = {rows}
                     │                                                            │
                     │  FilterController: local filters (no parrot_param)         │
                     └──────────────┬─────────────────────────────────────────────┘
                                    │ context: lane, filters, wireIndex, statuses
                      ┌─────────────▼──────────────┐
                      │ A2UINode (recursive by id) │──► WidgetFrame(origin, status) ──► <Component>.svelte
                      └────────────────────────────┘        └─ adapter(rows) → ECharts / grid / KPI
```

Every box except `WidgetFrame`, `originOf` and the control matrix EXISTS in `ui/src/lib/components/agents/canvas/a2ui/`.

---

## 6. Component tree to build (Svelte 5 + shadcn-svelte / bits-ui)

```
src/lib/a2ui/
├── A2UISurface.svelte          # engine host: mode, lane, contexts, toolbar (SurfaceToolbar)
├── A2UINode.svelte             # dispatcher by component name (registry map, §7)
├── WidgetFrame.svelte          # the "widget-like box": header, controls by origin, status, error, collapsible ParamPanel
├── SurfaceToolbar.svelte       # Reload / Refresh all / Server refresh / Pin / Open HTML / dashboard ParamPanel
├── ParamPanel.svelte           # form built from ParamSpec map: date (keywords), str, number, enum; locked → read-only badge
├── FilterBar.svelte            # ChoicePicker set: local filter vs parrot_param reload
├── engine/
│   ├── surface.svelte.ts       # class A2uiSurface: components ($state.raw Map), dataModel ($state), resolve(), origins, mode
│   ├── binding.ts              # JSON Pointer resolve (RFC 6901, ~0/~1, relative inside ChildTemplate scope)
│   ├── functions.ts            # 14 Basic Catalog functions (+ @index)
│   └── kind.ts                 # inferSurfaceKind / surfaceMode / originOf
├── linked/                     # COPY VERBATIM from ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/
│   ├── index.ts  fetch.ts  conditions.ts  dsl.ts  ref.ts  scheduler.ts  types.ts
│   └── (keep the *.test.ts and the parity fixtures — they are the contract)
├── adapters/
│   ├── chart.ts                # rows + Chart props → ECharts option  (a2ui-chart-adapter.ts is the seed)
│   ├── table.ts                # rows + columns → grid columns/formatters (typed: currency/percent/date…)
│   ├── kpi.ts                  # rows/0/<col> or scalar → {value, delta, trend, unit}
│   └── graph.ts                # GraphSpec → ECharts graph (A2UIGraph.svelte is the seed)
├── components/
│   ├── basic/  Text Image Icon Video AudioPlayer Row Column List Card Tabs Modal Divider Button TextField CheckBox ChoicePicker Slider DateTimeInput
│   ├── parrot/ Chart DataTable Map KPICard InfoCard Timeline Report Infographic HtmlDocument
│   ├── vizcore/ Graph (Chart/Series/Stat when a builder emits them — see §7.3)
│   └── Degraded.svelte         # keeps the original id; pushes {id, component, reason}
└── api/
    ├── surfaces.ts             # U2–U7 (axios ok: ai-parrot routes)
    ├── querysource.ts          # U8 (native fetch, bearer, 204 → [])
    └── types.ts                # wire types (reference §9) + generated LinkedSources.d.ts (pnpm generate from ui/schemas/LinkedSources.json)
```

### 6.1 Rules the engine must keep

- `$state.raw` for the component map (replaced wholesale on `updateComponents`), `$state` for `dataModel`
  (mutated at pointers; Svelte re-renders exactly the bound components).
- Resolve bindings **at render time**, never bake at load.
- A source update replaces `dataModel[key]` with `{rows}`; a failed fetch leaves the previous value (snapshot)
  untouched and only changes the status.
- Unknown component / unknown catalog → `Degraded.svelte` with the original `id`; never throw.
- Markdown in `Text` goes through a sanitizer (DOMPurify). `HtmlDocument.html` only inside
  `<iframe sandbox="allow-scripts">` without `allow-same-origin`.
- Theme: read `metadata.extensions.parrot_theme` / `parrot_layout` as hints; paint with the app's semantic tokens.
  viz-core rule: no colour/pixel from the wire, map semantic roles (`good/warning/critical/primary/neutral`) to tokens.

### 6.2 `WidgetFrame.svelte` contract

```ts
let { origin, status, title, locked, params, onRefresh, onParam, children }: {
  origin: Origin;
  status?: SourceUpdate;                      // undefined for inline widgets
  title?: string;
  params?: Record<string, ParamSpec>;         // only for origin.kind === 'source' on a linked surface
  locked?: string[];
  onRefresh?: () => Promise<void>;            // lane.refreshSource(key)
  onParam?: (name: string, value: unknown) => Promise<void>;   // lane.setParam(key, name, value)
  children: Snippet;
} = $props();
```

Behaviour: header = title + (status badge); right side = `Refresh` icon button **only** when `origin.kind ===
'source'` (D2/D3 — never for `shared`, `derived` or `inline`); a bits-ui `Collapsible` labelled "Filters" when
`origin.kind === 'source'` and `params` has at least one `editable` entry; body = `{@render children()}`;
footer = "data as of …" / "saved data" / "unavailable" / error detail from `status`. Use shadcn `Card`,
`Button variant="ghost" size="icon"`, `Collapsible`, `Badge`, `Skeleton` while `loading` and the snapshot is empty.

### 6.3 `ParamPanel.svelte`

Built from `ParamSpec` (`type`, `default`, `required`, `editable`, `accepts_keywords`) and `locked`. `type` is
the slug's own `cond_definition` type string as QuerySource stores it (free-form: `date`, `varchar`, `integer`,
`boolean`, …; copied verbatim by `QuerysourceToolkit._linked_params`, `parrot_tools/querysource/toolkit.py:653`),
so match it loosely:

| `type` (case-insensitive substring) / flags | Control |
|---|---|
| contains `date` or `time`, with `accepts_keywords` | `DatePicker` + a `Select` of keywords `TODAY, YESTERDAY, FDOM, LDOM, CURRENT_YEAR, CURRENT_MONTH, LAST_YEAR` |
| contains `date` or `time` | `DatePicker` (ISO `YYYY-MM-DD`) |
| contains `int`, `num`, `float`, `decimal` | `Input type=number` |
| contains `bool` | `Switch` |
| anything else or `null` | `Input`; when the FilterBar declares `options` for the same `parrot_param`, prefer the FilterBar control |
| name in `locked` (or `editable: false`) | read-only `Badge` with the value (UX hint only — security is QuerySource PBAC) |

Apply on blur / Enter, debounced 300 ms, through `lane.setParam(source, name, value)`. Never show a param that
is not declared: the lane ignores it anyway. The **dashboard** panel is the union of all `query_slug` sources'
params grouped by source key; derived keys never appear.

---

## 7. Catalog walk: every A2UI component and its widget frame

Catalog ids (EXISTS): Basic `https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json`; Parrot
`https://parrot.dev/catalogs/v1` (the surface default); viz-core
`https://ai-parrot.dev/a2ui/catalogs/viz-core/1.0/catalog.json`. A bare component name resolves under Basic or
Parrot without a per-component `catalogId`; `Graph` always carries the viz-core id explicitly.

### 7.1 Parrot presentation catalog (`parrot/outputs/a2ui/catalog/parrot/`)

| Component | Data-bearing field(s) | Linkable? | Frame | shadcn / library mapping |
|---|---|---|---|---|
| `Chart` | `data: {path}` → rows; `x`, `y[]`, `type` (14 types) | **yes** (binding root key) | `WidgetFrame` | ECharts via `adapters/chart.ts`; `layout: "half"` → half width |
| `DataTable` | `data: {path}` → rows; `columns[{name,type,title,format}]` | **yes** | `WidgetFrame` | shadcn data-table or `@revolist/svelte-datagrid`; server paging is a **widget-private** concern (`querylimit` + `_offset` on its own source, never on a shared one) |
| `KPICard` | `value`, `delta` (scalar or `{path}`), `trend`, `unit`, `comparisonPeriod` | **yes** (typically `/<key>/rows/0/<col>`) | `WidgetFrame` compact (no body chrome) | `Card` + `tabular-nums`; `parrot_trend` → icon |
| `Map` | `layers[i].data: {path}` (geojson or rows) | **yes** per layer | `WidgetFrame` | Leaflet; viewport/query props |
| `InfoCard` | `image` (URL or `{path}`) | binding only for the image | plain `Card` | `Card` + `Badge` |
| `Timeline` | `events[]` inline | no | plain `Card` | list |
| `Report` / `Infographic` | `sections[].components[{component, properties}]` (descriptor shape!) | children may be linked | **page**: title bar, `Tabs` when > 1 section; each nested descriptor goes through `WidgetFrame` | bits-ui `Tabs` |
| `FilterBar` | `filters[{column,label,options,multiple,param?}]` | `param` → `parrot_param` reload | its own bar (not a widget) | `ChoicePicker` set: `Select` / `Command`+`Popover`+`Badge` chips |
| `HtmlDocument` | `html` xor `srcUrl` (`tool_only`) | no | `WidgetFrame` without controls | sandboxed `<iframe>` |
| Form (`build_form`) | composed from Basic inputs + one `Button.action` | no | the surface itself | nothing special |

### 7.2 Basic catalog (18 primitives, `catalog/basic/`)

Layout `Row Column List Card Tabs Modal Divider`, media `Text Image Icon Video AudioPlayer`, inputs `Button
TextField CheckBox ChoicePicker Slider DateTimeInput`. None carries row data; **none gets a `WidgetFrame`**. They
are the lowered form of every Parrot composite, so the renderer must draw them all (reference §5.1 has the
prop/enum table and the shadcn mapping). A `Row` whose children are all `parrot_variant: kpi` cards is the KPI
grid. Inputs write back to `dataModel` at their `value.path`; `checks[]` render validation under the input.

### 7.3 viz-core catalog (`catalog/viz_core/`)

| Component | Status | Data field | Notes |
|---|---|---|---|
| `Graph` | EXISTS (`graph.py:63`, `A2UIGraph.svelte`) | `data: {path}` optional; `nodes`, `edges`, `groups`, `layout.positions` | `WidgetFrame`; node click is the standard `action` |
| `Chart` (viz-core) | **catalog-only** (`spec/catalog.json`; no Python builder emits it yet) | `data: {path}`, `x.type`, `series[]`/`seriesBy`, `size: inline\|tile\|hero`, `accessibleDescription` | reserve the registry key `(viz-core, Chart)`; render through the same `adapters/chart.ts` when it lands |
| `Series` | catalog-only | `field`, `mark`, `color.role`, `emphasis`, `labels` | child of viz-core `Chart` |
| `Stat` | catalog-only | `label`, `value`, `format`, `unit`, `delta`, `trend` | the viz-core KPI tile; `WidgetFrame` compact like `KPICard` |

Registry rule: key the dispatch map by `(catalogId, name)` because Parrot `Chart` and viz-core `Chart` share a
name (`catalog/__init__.py:98`).

---

## 8. Sequences

### 8.1 Open a dashboard from the sidebar

```
GET /api/v1/ui/surfaces?kind=dashboard           → pick surface_id
GET /api/v1/ui/surfaces/{id}                      → envelope + metadata (kind, refreshable, access)
mount A2UISurface(envelope, persistedSurfaceId=id, shareToken?)
  getDataSources → LinkedLane.start()
  per query_slug source (dependency order, siblings first):
     policy on_mount → POST QuerySource (U8) or POST …/sources/{key}/data (U6 if transform.python)
     rows → transform.ops? → dataModel[key] = {rows} → status ready
  derived sources recomputed after their parent
render; dashboard toolbar shows oldest snapshot_at
```

If `access === "shared"` (token) **skip** `LinkedLane.start()` — render the snapshot; the only live control is
`Server refresh` (U5), which runs as the owner.

### 8.2 User changes a dashboard param

```
ParamPanel.onParam(source="kpis", name="lastdate", value="TODAY")
  lane.setParam("kpis", "lastdate", "TODAY")     → re-fetch kpis with refresh:true → dependents recomputed
(optional) Persist: POST …/{id}/refresh {"params": {"kpis": {"lastdate": "TODAY"}}} → new snapshot stored
```

`/refresh` params are **not** persisted as descriptor defaults — always re-send the live params
(`A2UISurface.svelte:174`).

### 8.3 Pin a surface that arrived in chat

```
chat turn → a2ui_envelope (object or list) → for each createSurface:
  inferKind(root)  (Infographic/Report multi-section → dashboard; else widget)
  POST /api/v1/ui/surfaces {kind, title, envelope: createSurface, agent_id, session_id}  → surface_id
  (linked envelopes: the server takes a full snapshot at save time; 403 if no data-plane guard is configured)
store surface_id on the message; metadata.a2ui_surface_id may already carry it (FEAT-611)
```

### 8.4 Error handling cheat-sheet

| Signal | Meaning | UI |
|---|---|---|
| U8 `204` | zero rows | empty state, status `ready` |
| U8 `404` | slug unknown **or** denied (no oracle) | status `unavailable`, keep snapshot |
| U8 `401` | token expired | re-auth flow; do not blank |
| U6 `422 transformer_not_registered` / `transform_failed` / `transform_invalid_output` | server transformer problem | status `error`, show `code` |
| U5 `409 refreshable:false` | not recipe-backed, not linked | hide Reload |
| U5 `409 "stale refresh"` | someone persisted a newer snapshot | re-GET and re-mount |
| U5 `403` | no data-plane guard / PBAC denied | notice "refresh not permitted" |
| U5 `422`/`502` + `RecipeRunError` | recipe stage failed (`stage: data` → 502) | show `detail`, keep rows |
| `X-Parrot-Refresh-Warnings` | per-source soft failures on server refresh | toast each entry |
| `FrameSelectionError` | MultiQuery slug without `multi_output` | status `error`; the envelope is wrong, report to the agent owner |

---

## 9. Not in scope, and what it would take

**Cross-surface dashboards (a widget surface that references another surface's dataset).** Not implemented and
ruled out for v1 (reference §7.4 item 7: no cross-surface filter state). Everything the brief asks for is met
by the single-envelope linked dashboard. If the product later needs independently placed widgets that read a
shared dashboard's data (e.g. a widget embedded in a different page), the minimal design would be:

- a new source kind on the widget envelope, `{"kind": "dashboard_ref", "surface_id": "<uuid>", "key": "kpis", "target": "/kpis"}`,
  validated by `LinkedSources` and resolved by the lane with `GET /api/v1/ui/surfaces/{surface_id}` + the referenced
  key's descriptor; refresh would be delegated to the referenced surface's lane (shared in a page-level store);
- the server side would need the same reference check in `LinkedSurfaceService` so persisting/sharing a widget
  cannot leak a dashboard the viewer may not open.

This is a backend spec (FEAT) first, not a frontend task. Do not emulate it client-side by fetching two surfaces
and gluing them: snapshots, share tokens and refresh identity would drift.

**Other explicit non-goals**: URL/localStorage persistence of filter state; `transform.ref` modules without a CSP
plan on the host page (SRI authenticates bytes, not behaviour); deployment `@variables` on the wire.

---

## 10. Contract fixtures and tests to reuse

- **Wire schema**: `ui/schemas/LinkedSources.json` → `pnpm generate` → `LinkedSources.d.ts` (never hand-write
  descriptor types; Python ↔ TS drift must be a type error).
- **Parity fixtures** (both executors must reproduce them): `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/`
  — `conditions/*.json` (descriptor → body), `dsl/*.json` (ten ops), `parity/derived_dashboard.json`
  (fetch order, fetched keys, ignored params, rows), `parity/epson_dashboard_params.json`,
  `envelopes/linked_dashboard_{join,derived}.json`, `envelopes/linked_epson_dashboard.json`.
- **Reference TS lane + tests**: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/*.test.ts`
  (fetch, conditions, dsl, ref, scheduler, index, parity) and `A2UISurface.linked.test.ts`.
- **Vanilla reference**: `examples/a2ui/static/{linked.js,dsl.js,renderer.js}` — the same lane with no framework,
  plus `examples/a2ui/client.py --check` which asserts the Polestar numbers end to end.
- **Golden lowered trees**: `packages/ai-parrot/tests/outputs/a2ui/golden/*_lowered.json`.
- **A2UI schemas to vendor**: `parrot/outputs/a2ui/catalog/basic/spec/*.json`, `catalog/viz_core/spec/catalog.json`;
  the Parrot catalog document is generated with `write_catalog_definition` (reference §10).

Definition of done for the renderer: the parity fixtures pass under vitest, `examples/a2ui` renders with the
four Polestar numbers, a static Flex dashboard reloads through U5, and a share-token open never issues a U8 call.
