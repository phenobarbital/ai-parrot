# Report Builder — ai-parrot inventory and analysis

> **Date**: 2026-10-01 · **Base**: `ai-parrot` dev `dc3e3a548` · navigator-svelte dev `8c34c8d26` · navigator-api `a3b38a1d`
> **Method**: an exhaustive read-only review in 8 parallel lanes. Every claim cites `file:line` in the annexes (`inventory/`).
> **Companion document**: `navigator-svelte/docs/audits/report-builder-2026-10/inventory-and-analysis.md` (front-end side, what to port or build).

## 0. Executive summary

1. **About 80% of the engine already exists.** Everything below is implemented and tested (all FEATs 100% in `sdd/tasks/index`):
   - A2UI v1.0 wire format with validation (FEAT-470/273);
   - 3 component catalogs, 29 components;
   - live data bound to QuerySource, with a DSL, an executor, server refresh and a TS client lane (FEAT-598/611);
   - persisted surfaces with visibility and share tokens (FEAT-492/535);
   - recipes (data → transform → layout → render) with a Pg store and a scheduler (FEAT-324/528);
   - 6 renderers (HTML, SSR, PDF, ECharts, Adaptive Cards, Folium) and a design system with themes.
2. **What's missing is the authoring layer**, not rendering:
   - no report/page/template entity;
   - no editing of an already-saved surface, and no versioning;
   - no API for editing individual components;
   - no catalog palette over HTTP;
   - infographic templates and themes are not persisted;
   - export and scheduling are fragmented.
3. **Strongest prior art for "builder + versions"**: `parrot-formdesigner`. It has row-per-version storage, publish/promote, batched `/operations` with `If-Match`, a granular `EditToolkit`, a palette endpoint (`/api/v1/form-controls`) and multi-format rendering. **The report builder should copy that pattern** over A2UI surfaces.
4. **Navigator (front end) already renders A2UI** (all of the Parrot catalog except `Graph`) at `[programs]/reporting`, with save, share and refresh. It has explicitly decided **not to compile surfaces to Navigator widgets** (FEAT-560). So the report builder is **an A2UI authoring tool**, not a new type of Navigator dashboard.
5. **Recommendation**: build a **`Report` (document) entity** in ai-parrot as a set of A2UI pages with a layout, versions, parameters and templates. Expose a builder-style API (operations, palette, publish, export, schedule). In Navigator, build the editor reusing its grid (`svelte-grid-extended`, edit mode, snap, undo), its A2UI renderer and its schema-driven settings drawers.

---

## 1. Inventory (summary; detail in the annexes)

| Lane | Annex | Contents |
|---|---|---|
| P1 | `inventory/P1-parrot-endpoints.md` (+ `_core.md`, `_admin_bots.md`, `_formdesigner.md`) | All ai-parrot HTTP/WS/SSE endpoints by domain: surfaces, A2UI runtime, infographic, recipes, artifacts, legacy dashboards, AgentTalk, QuerySource, formdesigner, studio/admin/scheduler |
| P2 | `inventory/P2-parrot-components-models.md` | Catalogs and components, validation, builders, linked data, renderers, infographics/recipes, persistence, agent tools, formdesigner |
| P3 | `inventory/P3-parrot-admin-ui.md` | Admin UI (Svelte 5): canvas, tabs, A2UI renderer, linked lane, infographic UI, editors, API clients, dependencies, portability |
| P4 | `inventory/P4-parrot-prior-art.md` | Prior SDD specs and proposals with status, decisions already made, open items |
| N4 | `inventory/N4-navigator-api-backend.md` | navigator-api (dashboards, widgets, templates, widget_types) and the parrot `NavigatorToolkit` |

### 1.1 Relevant endpoints (key ones)

| Domain | Endpoints | State |
|---|---|---|
| A2UI surfaces | `GET/POST /api/v1/ui/surfaces`, `GET/PATCH(visibility)/DELETE /{id}`, `POST /{id}/refresh`, `POST/DELETE /{id}/share[/{token}]`, mirror `/api/v1/agents/{id}/a2ui/surfaces/{sid}` | ✅ No PUT for envelope/title, no versions, no clone |
| A2UI runtime | `POST /api/v1/agents/{id}/a2ui`, SSE, `/capabilities`, deep-link `/api/v1/a2ui/resume/web` | ✅ `/capabilities` returns IDs only, not the catalog |
| Infographic | LLM generation, `/render` (LLM-free, async jobs), `GET/POST /api/v1/agents/infographic/{templates,themes}` | ⚠️ templates/themes kept **in memory** (lost on restart) |
| Recipes | `/api/v1/infographic_recipes` CRUD + `/run` | ⚠️ **return 500 in the stock host** (`register_recipe_routes` is never called) |
| Artifacts | `/api/v1/threads/{sid}/artifacts` (+ download, signed public HTML) | ✅ per thread; `CanvasDefinition` is not validated |
| Legacy dashboards (Mongo) | tabs and widgets | ⛔ `ENABLE_DASHBOARDS=False`, no auth or owner check |
| AgentTalk | output modes `a2ui`, `infographic`, `interactive`, `structured_*`, streaming SSE/NDJSON/chunked/WS | ✅ (FEAT-611 adds the linked envelope lift in `ask` and `ask_stream`) |
| Form designer | form CRUD, batched `/operations` + `If-Match`, publish/versions, palette `/form-controls`, multi-format render | ✅ **the builder model to copy** |
| Scheduler | `navigator.agents_scheduler` (PDF email-report callbacks) | ⚠️ no owner scoping; not linked to surfaces |

### 1.2 Components and models

| Piece | Where (summary) | State |
|---|---|---|
| Parrot catalog | Chart, DataTable, KPICard, Map, FilterBar, Infographic, Report, Timeline, InfoCard, HtmlDocument | ✅ Chart/DataTable/KPICard/Map/Graph bind data by `{"path"}` |
| Basic catalog | 18 primitives + 14 functions | ✅ |
| viz-core | `Graph` (Chart/Series/Stat exist in the spec but are not registered) | ⚠️ partial |
| Validation | `validate_envelope` (structure, LLM/TOOL gates, linked sources) | ⚠️ **does not validate props against each component's JSON Schema** |
| Builders | `build_linked_surface`, `qs_build_linked_surface`, `qs_build_linked_dashboard` (fixed layout) | ✅ fixed layouts only |
| Linked data | `LinkedDataSource` (only `query_slug`), 11-op DSL, executor, `LinkedSurfaceService`, `transform.ref` HMAC manifest | ✅ (known limits: flat MultiQS conditions, `request.limit`) |
| Renderers | interactive-html, ssr_html, pdf (weasyprint), echarts, adaptive_cards, folium | ✅ no PNG |
| Infographic | 19 blocks, 9 templates (incl. `multi_tab`), InfographicToolkit (11 tools), `publish_surface` | ⚠️ registries in memory |
| Recipes | v2 schema, 8 transformers, File/Redis/Pg stores, RecipeRunner, scheduler callback | ✅ no versions (PK `(name, owner)`) |
| Persistence | `navigator.ui_surfaces` (kind dashboard/infographic/widget, recipe, visibility) + `ui_surface_shares` | ✅ overwrite only, no history |
| Form designer | `FormSchema` (45 field types), 9 renderers (incl. A2UI), row-per-version, publish, `EditToolkit` | ✅ reference pattern |

### 1.3 Admin UI (Svelte) — what can be ported to Navigator

- **Pure TS, highly portable**: `a2ui-types`, `a2ui-binding`, `a2ui-format`, `a2ui-kind`, `a2ui-chart-adapter`, and the full linked lane `a2ui/linked/*` (dsl, fetch, scheduler, conditions, ref, with Python parity tests).
- **Medium-high**: `A2UISurface`/`A2UINode`/`A2UIGraph` (they depend on shadcn tokens, AppTabs, ECharts and auth/config).
- **Note**: much of the admin canvas **came from navigator-frontend-next**, so porting it back is mostly a reverse diff.
- **Admin UI limits**: tabs are not persisted; editing is up/down only (no grid or DnD); A2UI is render-only; there are 3 parallel block models (CanvasBlock, InfographicBlock and A2UI); a probable bug where infographic export looks for `.echarts-container` but charts are drawn with layerchart.

---

## 2. Gap matrix (consolidated)

| # | Gap | Evidence (annex) | Priority for the builder |
|---|---|---|---|
| G1 | **No Report/Page/Template entity** (document → pages → components with bindings) | P1 §14.1, P2 G1/G4 | **P0** |
| G2 | **No editing or versioning** of surfaces/recipes/templates (overwrite only) | P1 §14.2-3, P2 G2 | **P0** |
| G3 | **No component-level editing API** (add, move or update a component; `UpdateComponents` exists on the wire but has no server CRUD) | P2 G6 | **P0** |
| G4 | **Catalog not discoverable over HTTP** (`export_catalog_definition` has no route) → no palette | P1 §14.7 | **P0** |
| G5 | **Props not validated** against each component's JSON Schema | P2 G8 | P1 |
| G6 | **Page/board layout model** (positions, sizes, page breaks, header/footer); today only Row/Column/Tabs and `full/half` | P2 G4/G7 | **P0** |
| G7 | **`Report` composite half-wired** (no builder, no adapter, no pagination, TOC or numbering) | P2 G7 | P1 |
| G8 | **Templates and themes not persisted** and not tenant-scoped; there are 5 "template" concepts that have never been unified (one dead: `outputs/templates`) | P1 §14.5, P2 G3/G13/G15 | **P0** |
| G9 | **Recipes not mounted in the stock host** (500) | P1 §14.6 | P1 (quick fix) |
| G10 | **Refresh only per whole surface** (no per-component/source refresh, no partial `dataModel`) | P1 §14.4 | P1 |
| G11 | **Report-level parameters** (shared filters/params across pages and components) | P2 G11 | P1 |
| G12 | **Fragmented export**: no surface→PDF/PNG/XLSX/PPTX endpoint, no export job | P1 §14.10, P2 G10 | P1 |
| G13 | **Scheduling and subscriptions** for surfaces/reports (only recipes have a callback) | P1 §14.12, P2 G12 | P2 |
| G14 | **Organisation** ("my reports": folders, tags, pins); `threads.py` is not mounted | P1 §14.14 | P2 |
| G15 | **Collaboration / real-time change channel** | P1 §14.13 | P3 |
| G16 | **Linked data limited to `query_slug`** + MultiQS ignores flat conditions (F020 FEAT-611) | P2 G11, FEAT-611 F020 | P1 |
| G17 | **Security debt** in neighbouring endpoints: legacy dashboards without auth, scheduler without owner scoping, formdesigner audio WS | P1 §E, §14.8 | P1 (outside the builder, do not reuse) |

---

## 3. Recommended architecture

### 3.1 Domain model (new, in ai-parrot, next to `ui_surfaces`)

```
Report (document / template)
  report_id, tenant, owner, title, kind: template|report, status: draft|published,
  current_version, visibility (private|tenant|groups), tags, folder
ReportVersion (one row per version, like formdesigner)
  report_id, version, schema_version, created_by, created_at, note,
  definition: {
    parameters: [{name, type, default, required, editable}],      ← report-level filters (G11)
    theme: {design_system_theme | theme_ref},
    pages: [{
      page_id, title, size: screen|A4|Letter, orientation, header?, footer?,
      layout: {grid: 12, items: [{component_id, x, y, w, h}]},       ← same model as Navigator (12 cols)
      surface: <A2UI v1.0 createSurface>                               ← components + parrot_data_sources
    }]
  }
ReportShare / ReportSchedule  → reuse ui_surface_shares and agents_scheduler (FK to report_id)
```

- **Each page is an A2UI v1.0 surface.** That reuses validation, renderers, linked data, refresh and Navigator's renderer. The `layout` grid lives alongside, in the same 12-column format as `navigator.dashboards.attributes.widget_location`, but **keyed by `component_id`, not by title**. This avoids the known rename-breaks-layout bug.
- **Template = Report with `kind=template`**. Instantiating one copies the definition and resolves its parameters. That unifies G8: infographic templates are migrated, and the dead `outputs/templates` is removed.

### 3.2 API (copied from the formdesigner pattern)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/reports/catalog` | Palette: components + JSON Schema of props + `linkable` (from `export_catalog_definition`), plus themes |
| GET/POST | `/api/v1/reports` | List (filters: kind, tag, folder, owner) / create (blank or `from_template`) |
| GET | `/api/v1/reports/{id}[?version=]` | Definition (draft or a version) |
| POST | `/api/v1/reports/{id}/operations` + `If-Match` | **Batched edit ops**: `add_page`, `move_page`, `add_component`, `update_props`, `move/resize` (layout), `bind_source`, `remove_*`, `set_parameter`, `set_theme`. Validates props against JSON Schema (closes G5) |
| POST | `/api/v1/reports/{id}/publish` · GET `/versions` · POST `/versions/{v}/promote` | Versioning (G2) |
| POST | `/api/v1/reports/{id}/clone` · `/save-as-template` | Duplicate / template |
| POST | `/api/v1/reports/{id}/render?format=html\|pdf\|png\|xlsx[&page=]` | Unified export (G12); PDF via weasyprint/print2pdf; PNG via a headless renderer |
| POST | `/api/v1/reports/{id}/refresh[?page=&source=]` | Refresh per report, page or source, with partial `dataModel` (G10) |
| POST/DELETE | `/api/v1/reports/{id}/share[/{token}]` · PATCH visibility | Reuses the `ui_surfaces` share lane |
| POST/GET | `/api/v1/reports/{id}/schedules` | Delivery (card + URL, per FEAT-430) via `agents_scheduler` (G13) |

### 3.3 Agent

- **`ReportBuilderToolkit`** (same style as formdesigner's `EditToolkit`): `report_create`, `report_add_component`, `report_bind_source` (reusing `qs_build_linked_surface`), `report_update_props`, `report_publish` and `report_list`. All TOOL-origin, so it satisfies the "only tools may carry data sources" rule.
- **"Add to report" from chat**: a canvas widget (a linked surface) is converted into an `add_component` operation on a chosen report.

### 3.4 Constraints already decided (from prior specs, not to be renegotiated)

- No code inside definitions: registered transformers or the 11-op DSL.
- Output always validates against A2UI v1.0.
- Refresh is deterministic, with no LLM.
- Schema drift fails fast.
- Only TOOL-origin output carries `parrot_data_sources`.
- HTML is self-contained, with no CDN.
- Delivery is card + URL; no public static hosting.
- Navigator: do not compile surfaces into widgets (FEAT-560). The dashboard flag is `attributes.artifact_type: v1-html|v2-a2ui`. Scheduling goes through the NavAPI wrapper (FEAT-511).

---

## 4. Proposed roadmap (ai-parrot)

| Phase | Deliverables | Closes gaps |
|---|---|---|
| **0. Quick wins** (S) | Mount recipe routes in the stock host; persist infographic templates/themes (Pg, tenant-scoped); `GET /api/v1/a2ui/catalog` route; fix the infographic export `.echarts-container` bug | G9, G8 (partial), G4 |
| **1. Report core** (L) | `Report`/`ReportVersion` model + store (Pg, `navigator` schema); CRUD + publish/versions + clone/template; prop validation against JSON Schema | G1, G2, G5, G8 |
| **2. Edit operations** (M) | `/operations` endpoint + `If-Match`; `ReportBuilderToolkit` for agents; "add to report" from AgentTalk | G3 |
| **3. Layout and pages** (M) | Grid model keyed by `component_id`, pages with size/orientation/header/footer; `Report` composite wired into the renderers (pagination, TOC) | G6, G7 |
| **4. Data and parameters** (M) | Report-level parameters propagated to the sources; per-source refresh with partial `dataModel`; fix flat MultiQS conditions | G10, G11, G16 |
| **5. Export and delivery** (M) | Unified `/render` (HTML/PDF/PNG/XLSX); report scheduling via the scheduler + Teams card | G12, G13 |
| **6. Organisation** (S) | Tags/folders/pins | G14 |

---

## 5. Decisions needed before the spec

1. **Persistence plane**: today Navigator consumes surfaces **through FieldSync** (`/api/v1/{tenant}/ui/surfaces`), not straight from parrot. Should reports live in parrot (recommended: next to `ui_surfaces`) with FieldSync proxying, or in FieldSync?
2. **Native Navigator widgets inside a report**: is a `NavigatorWidget` component (embed by `widget_id`) allowed, to reuse the 85 existing types? Or do reports use A2UI components only? FEAT-560 rejected compiling surfaces to widgets, not embedding widgets.
3. **Print/PDF model**: is page size/page break needed in the first iteration (a document report), or are interactive boards enough to start?
4. **Charting**: should ECharts be the only engine for the builder? Navigator already uses ECharts for Chart; parrot admin uses layerchart.
5. **Relation to the agent "Dashboard Builder"** from Navigator's `SPEC_SuperUserToolbar.md`: its endpoint (`/api/agent/dashboard-builder`) does not exist. Should it be absorbed into the `ReportBuilderToolkit`?

## 6. Side findings (outside the builder, worth a ticket)

- `VIZ/formats/jinja2.py:11` registers `OutputMode.JINJA2`, which the enum does not have (dead or broken code).
- `handlers/threads.py` is never mounted.
- Legacy dashboards have no auth (`ENABLE_DASHBOARDS=False`).
- The scheduler has no owner scoping.
- The formdesigner audio WS auth-exclude path doesn't match the real route.
- Linked surfaces have 3 open major ledger items: `request.limit` is dropped; empty snapshots break KPI bindings; slug authorization does not fail closed.
- navigator-api: the layout PATCH writes the legacy `widget_location` column, while the UI and parrot use `attributes.widget_location`.

---

## Annexes

The full inventories with `file:line` citations are in `docs/report-builder/inventory/`:
`P1-parrot-endpoints.md`, `_core.md`, `_admin_bots.md`, `_formdesigner.md`, `P2-parrot-components-models.md`, `P3-parrot-admin-ui.md`, `P4-parrot-prior-art.md`, `N4-navigator-api-backend.md`.
