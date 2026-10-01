---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-server, ai-parrot-tools, ai-parrot-visualizations, parrot-formdesigner, admin-ui, docs]
tags: [report-builder, a2ui, dashboards, linked-surfaces, templates, scheduling]
---

# Brainstorm: Report Builder (interactive boards over A2UI, editable by people and agents)

**Date**: 2026-10-01
**Author**: Javier León
**Status**: exploration
**Recommended Option**: A
**Inputs**:
- `docs/report-builder/inventory-and-analysis.md` and its annexes (PR #1543);
- `navigator-svelte/docs/audits/report-builder-2026-10/` (PR #1859);
- Code Context verified on ai-parrot dev `f01a600f1`, navigator-svelte dev `8c34c8d26` and fieldsync `9254d2ed`.

---

## Problem Statement

Today a dashboard or report with live data can only be made in two ways, neither connected to the other:

- **An agent generates an A2UI surface.** It is saved in `navigator.ui_surfaces`, viewed in Navigator at `[programs]/reporting`, and can be shared and refreshed. But **it cannot be edited** after it is saved. There are no versions and no templates. The layout is fixed by whichever tool emitted it.
- **Someone builds a Navigator dashboard** with the 85 widget types and edits it in the grid. But it is not A2UI, it has no versions, no share tokens and no scheduling per board, and FEAT-560 decided not to compile surfaces into widgets.

Nobody can **compose, edit, version, template, share and schedule** a multi-page interactive board, whether by hand in a visual editor or through an agent on the same document. The rendering engine already exists (A2UI v1.0, 29 components, linked data with refresh, surfaces with share and visibility, recipes, scheduler, renderers); what is missing is the **authoring layer**.

**Affected users**:
- analysts and managers who build boards;
- agents that today emit one-off surfaces;
- report consumers (share, Teams delivery).

## Constraints & Requirements

**Decided in discovery (3 rounds, 2026-10-01):**
- **Flow**: feature → `dev`.
- **v1 scope = interactive board**: pages of A2UI v1.0 components on a 12-column grid, live data, filters, refresh, HTML/PNG export. **Paginated PDF** (page size, page breaks, header/footer) is phase 2.
- **Persistence in ai-parrot**, next to `navigator.ui_surfaces`. Navigator consumes it **through FieldSync**. Verified: FieldSync is not an HTTP proxy. It mounts parrot handlers in-process with a programme scope (`ScopedUISurfacesHandler`, `ProgramScopedSurfaceStore`). The reports lane must follow the same pattern.
- **Authoring = visual editor + agent over ONE operations API** (the formdesigner pattern, where `EditToolkit` and HTTP share the same `_apply_*` functions).
- **Native Navigator widgets** can be embedded through an A2UI `NavigatorWidget` component (by `widget_id`). FEAT-560 still holds: surfaces are not compiled into widgets. In server-side export, an embedded widget is a **placeholder with a deep link**.
- **Typed global parameters** at report level, bound to the sources. A global FilterBar re-queries every bound source.
- **Absorb** the SuperUserToolbar "Dashboard Builder" into a `ReportBuilderToolkit`. Verified: it was only a front-end stub and has been deleted, so there is nothing to migrate.
- **v1 must-haves**:
  - versions + publish (draft/published, history, promote);
  - templates (save-as, gallery, instantiate);
  - share + visibility (private/tenant/groups, tokens);
  - scheduled delivery (Teams card + URL).
- **Charting: ECharts only.** ⚠️ Verified conflict: `InteractiveHTMLRenderer` draws with vendored Chart.js, and `EChartsRenderer` only emits the first chart. See Open Questions.

**Inherited from prior specs (do not renegotiate):**
- No code inside definitions: registered transformers or the 11-op DSL only.
- Every page validates against A2UI v1.0.
- Refresh is deterministic, with no LLM.
- Schema drift fails fast.
- Only TOOL-origin output may carry `parrot_data_sources`.
- `LinkedSurfaceService` refuses to run without a data-plane guard (fail-closed).
- HTML is self-contained, with no CDN.
- Delivery is card + URL; no public static hosting.
- Navigator: `src/lib/fn/**` must not be touched; editing is desktop-only (viewing must work on mobile); Svelte 5 runes without mixing with legacy stores; `browser` guards for SSR; tests use `@testing-library/svelte/svelte5`.

**Other technical constraints found:**
- **Route collision:** FieldSync already serves `/api/v1/reports/*` (FEAT-308 exports and schedules), and navigator `reports-api.ts` calls `/api/v1/reports/schedule`. The new resource needs a **distinct segment**.
- **Existing bug:** the FieldSync `ProgramScopedSurfaceStore` wrapper does not accept `expected_updated_at` in `update_envelope`. Linked refresh through FieldSync breaks once FieldSync installs the FEAT-598 wheel. This must be fixed in the same effort.
- **No container in the catalog:** there is no Page, Grid or Dashboard component and no 12-column layout. The only layout hint is `parrot_layout` (report|analytics|print).
- **Navigator dashboard grid:** `svelte-grid-extended` (12 cols, `itemSize.height` 10, `gap` 5) inside `Dashboard.svelte` (2028 lines, legacy mode), with layout **keyed by widget title**. It is reusable for UX, but the report layout must be keyed by `component_id`.

---
## Options Explored

### Option A: Report document over A2UI pages, with a formdesigner-style API

A new **`Report` / `ReportVersion` entity in ai-parrot** (Pg, `navigator` schema, next to `ui_surfaces`). Each version holds:
- a definition with `parameters[]` (typed), `theme`, and `pages[]`;
- per page: `layout` (12-column grid keyed by `component_id`) and `surface` (an A2UI v1.0 `createSurface` with its `parrot_data_sources`).

Versions use one row per version, like formdesigner. `status` is draft/published and `current_version` is promotable.

**API (distinct segment, e.g. `/api/v1/report-builder/…`):**
- `catalog` (palette = `export_catalog_definition` + `linkable` + `NavigatorWidget`);
- CRUD;
- `operations` + `If-Match` (412 on conflict);
- `publish` / `versions` / `promote`;
- `clone` / `save-as-template` / `from_template`;
- `render` (HTML per page);
- `refresh` (per page or source, with parameters);
- `share` / `visibility` (reusing the `ui_surface_shares` lane);
- `schedules` (a new scheduler callback, modelled on `RunInfographicRecipeCallback`).

**Agent side:** a `ReportBuilderToolkit` uses the same `_apply_*` ops as HTTP.

**FieldSync:** `ScopedReportBuilderHandler` + `ProgramScopedReportStore` + `setup_report_builder(app)`, copying the surfaces pattern.

**Navigator:** a `reporting/builder/[report_id]` route that reuses the grid UX, the A2UI renderer, `JsonSchemaDrawer` and the ported linked lane.

✅ **Pros:**
- Clean model with stable ids: editing, versions, templates and pages are first-class.
- Reuses the whole engine: validation, linked data, refresh, renderers, shares, scheduler.
- The agent and the editor share the same operations, so there is no drift. This is a pattern already proven in formdesigner.
- Every page stays a standard A2UI surface, so the current Navigator viewer, export and FieldSync tenancy keep working.
- Templates are just `kind=template` on the same entity.

❌ **Cons:**
- A new entity, with migration and store.
- Ops API, palette route, FieldSync lane and the Navigator editor: several deliverables across 3 repos.
- Duplicates part of `ui_surfaces` (share/visibility) unless it is referenced by FK.

📊 **Effort:** High (backend M–L, FieldSync S–M, Navigator L)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncpg` / existing pg store | `reports`, `report_versions`, `report_shares` | same plane as `PgUISurfaceStore` |
| `pydantic` v2 | definition, ops and parameter models | already in use |
| `jsonschema` | validate props against `ComponentDefinition.schema` | closes a gap in `validate_envelope` |
| `svelte-grid-extended` ^1.2.1 | builder grid (Navigator) | already a dependency; no new lib |
| `echarts` | single charting engine | Navigator already uses it; parrot server HTML needs alignment (see OQ) |
| APScheduler (existing) | scheduled delivery | via `CALLBACK_REGISTRY` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` + `handlers/models/ui_surfaces.py`: share tokens, visibility, scope resolver, refresh.
- `packages/ai-parrot/src/parrot/outputs/a2ui/linked/{service,executor,models}.py`: execution, refresh and per-source params.
- `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/{__init__,export}.py`: registry, `validate_envelope`, `export_catalog_definition`.
- `packages/parrot-formdesigner/…/services/form_version.py`, the operations handler, `tools/edit_toolkit.py`: the versions + ops + toolkit pattern.
- `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` (`qs_build_linked_surface`, `qs_build_linked_dashboard`): source binding and the board-builder precedent.
- Scheduler: `CALLBACK_REGISTRY`, `RunInfographicRecipeCallback`, `NotificationMixin.build_teams_card/send_teams_card`.
- FieldSync: `fieldsync/surfaces.py` (`ScopedUISurfacesHandler`, `ProgramScopedSurfaceStore`), `apps/tenancy/seam.py` (`programme_route_prefix`).

---

### Option B: Extend `ui_surfaces` (an editable surface with versions)

No new entity. Instead:
- add `kind=report` and `kind=template` to `UISurfaceKind`;
- add `PUT/PATCH envelope` + `If-Match` to `/api/v1/ui/surfaces/{id}`;
- add a `ui_surface_versions` table;
- represent pages as `Tabs` inside a single envelope, with the 12-column grid in `metadata.extensions.parrot_layout_grid`;
- keep parameters as per-source `ParamSpec` plus a top-level FilterBar.

Edits would be whole-envelope (the client sends the full document), or a minimal set of JSON-Patch ops.

✅ **Pros:**
- Least new surface area. Navigator `reporting` and the FieldSync surfaces lane would work almost for free, since they already mount `UISurfacesHandler`.
- Shares, visibility and refresh are already there.

❌ **Cons:**
- One giant envelope per report: concurrency, diffs and partial refresh become costly.
- Pages as `Tabs` don't map to the per-page grid.
- Without semantic ops, the agent and the editor diverge (JSON-Patch is not validatable against the catalog per op).
- Mixes instances (agent snapshots) with authored documents in the same table.
- `kind` and the overloaded `envelope` semantics break assumptions in FEAT-492/535/598.

📊 **Effort:** Medium

📦 **Libraries / Tools:** `jsonpatch` (if JSON-Patch is chosen), the rest as in A.

🔗 **Existing Code to Reuse:** the same `ui_surfaces` plane and the existing FieldSync surfaces lane.

---

### Option C: Reports as Navigator dashboards (navigator-api / `navigator.dashboards`)

Each report is a `navigator.dashboards` row with `attributes.artifact_type: v2-a2ui`. Each component is a `navigator.widgets` row with a new A2UI `widget_type` that renders its sub-envelope. The layout is the `widget_location` that already exists, and templates are `widgets_templates`.

✅ **Pros:**
- Reuses the existing editor (edit mode, snap, undo, Widgets panel, `cloneWidget`) and the 85 widgets with no embedding needed.
- Familiar to the Navigator team.

❌ **Cons:**
- **Contradicts FEAT-560** (do not compile surfaces into widgets).
- navigator-api models are `strict=True`: every new field needs a migration.
- The layout is keyed by **title**.
- No versions, no share tokens, no ownership checks on widget PATCH/DELETE.
- Linked data, refresh and the data-plane guard all live in parrot, so it would mean two-plane data plumbing.
- `NavigatorToolkit` writes SQL directly. Agents would have to operate on two models.

📊 **Effort:** High (plus architectural debt)

🔗 **Existing Code to Reuse:**
- navigator-api `resources/dashboards`, `resources/widgets`;
- the navigator-svelte `Dashboard.svelte` + helpers;
- `parrot_tools/navigator/toolkit.py`.

---

### Option D (unconventional): Recipe-centric reports

The report **is a recipe**: `InfographicRecipe` v2, made of data → registered transformers → layout → render. The editor edits the recipe (sources, transforms and the layout of catalog components). Every view or delivery **regenerates** the surface deterministically with `RecipeRunner`. Templates are parameterized recipes, and scheduling reuses `RunInfographicRecipeCallback` without changes.

✅ **Pros:**
- Maximal determinism and reproducibility (no persisted snapshot that can drift).
- Scheduling and delivery already have a callback.
- The infographic-builder brainstorm already recommended this layer (Option A there), and its 7 questions are resolved.

❌ **Cons:**
- `LayoutSpec` is a single root with no stable component ids or per-component editing, so the visual editor would have to reinvent it.
- **Recipe routes are not mounted** in the stock host (`register_recipe_routes` has no caller outside tests).
- No live linked lane per component: refresh is a full recipe re-run.
- Recipes are keyed `(name, owner)` with no versions.
- Interactivity (FilterBar → individual sources) fits poorly.

📊 **Effort:** Medium–High

🔗 **Existing Code to Reuse:** `parrot/outputs/a2ui/recipes/*` (models, runner, stores), `RunInfographicRecipeCallback`.

---

## Recommendation

**Option A** is recommended because it is the only one that meets all four discovery decisions at once:

1. **Visual editor + agent over one API.** Semantic ops plus `If-Match`, shared by HTTP and the toolkit, is the formdesigner pattern. In B, JSON-Patch or whole-envelope edits make the editor and agent drift. In C, there would be two models (navigator SQL and A2UI).
2. **Versions, templates, share and schedule as first-class features.** A has its own versions and a `kind=template`. B mixes authored documents with agent snapshots. C has no versions or share tokens. D has no versions or editable layout.
3. **Persistence in parrot, consumed through FieldSync.** A copies exactly the surfaces lane that FieldSync already mounts in-process. C puts persistence in navigator-api.
4. **FEAT-560 holds.** Pages stay standard A2UI; Navigator widgets are only *embedded* through `NavigatorWidget`.

**What we give up:** A costs more up front than B (a new entity and a new lane in FieldSync). We accept that to avoid the per-envelope concurrency, mixed semantics and agent/editor drift of B. To limit duplication, A **reuses** the `ui_surfaces` pieces: share tokens and visibility (FK or the same pattern), the scope resolver, and the refresh service. From D it takes the **registered transformers** and the **callback pattern** for scheduling, without adopting the single-root layout.

---

## Feature Description

### User-Facing Behavior

- **In Navigator (desktop):**
  - From `[programs]/reporting`, "New report" (blank or from a template) opens `reporting/builder/[id]`.
  - The editor has a **page bar** (add, rename, reorder) and a **12-column grid** with drag/resize, snap guides and undo (the same UX as dashboard edit mode).
  - A **component palette** (KPICard, Chart, DataTable, FilterBar, Map, InfoCard, Timeline, HtmlDocument, Graph, NavigatorWidget) is driven by the catalog endpoint.
  - An **inspector** (`JsonSchemaDrawer`) edits the props schema of each component. It includes a **data source picker** (QuerySource slug + fields/filters/group_by + DSL transforms) and **parameter binding**.
  - A **parameters panel** declares typed global parameters (date/range, select, multi-select, text, number) with defaults. A global FilterBar changes them and re-queries every bound source.
- **Live preview** with real data, through the linked lane ported from parrot.
- **Toolbar**: save (ops), publish, version history/promote, save as template, preview, export (HTML; PNG on the client), share (token + visibility), schedule delivery (Teams card + URL).
- **Viewing** (desktop and mobile): the published version, with refresh and parameters. Shared links work without an account per the token rules. Embedded Navigator widgets render live.
- **From agent chat**: "Add to report" on a canvas surface turns it into an `add_component` on a chosen report. The agent can also create or edit reports through the `ReportBuilderToolkit` ("build me a visits board by program with a date filter").

### Internal Behavior

1. **Model:** `Report` (id, tenant/programme scope, owner, title, kind report|template, status, current_version, visibility, tags) and `ReportVersion` (version, schema_version, definition, created_by/at, note). The definition holds `parameters[]`, `theme`, and `pages[]` (`page_id`, title, `layout.items[{component_id,x,y,w,h}]`, `surface` A2UI v1.0).
2. **Operations:**
   - `POST …/operations` with `If-Match: <draft_version>` applies a batch of semantic ops: add/move/rename/remove page; add/update_props/move/resize/remove component; bind_source/unbind_source; set/remove parameter; bind_parameter; set_theme.
   - Each op validates against the catalog: props against the component's JSON Schema, linked sources through `validate_envelope` with TOOL origin, layout without overlaps.
   - Each op is atomic per batch and returns the new draft version (412 on a stale version).
   - The `ReportBuilderToolkit` exposes the same ops to agents.
3. **Data:** each data component points at a `LinkedDataSource` (query_slug). Global parameters resolve into each source's placeholders/filters via `bind_parameter`. Refresh runs `execute_sources` per page or source under the data-plane guard. Because flat MultiQS conditions don't reach child queries, multiquery sources either pin their children's conditions or the propagation gets fixed (see OQ).
4. **Publish/versions:** publish freezes the draft as a numbered version (`current_version`). Promote restores one. Viewers read the published version, and the editor reads the draft.
5. **Templates:** a report with `kind=template` and parameters. `from_template` copies the definition and applies parameter values. The gallery is filtered by tenant/programme.
6. **Share/visibility:** the same semantics as `ui_surfaces` (private/tenant/groups, opaque revocable tokens). Viewing through a token runs refresh as the **owner**, the same rule as surfaces.
7. **Delivery:** a `RunReportCallback` registered in `CALLBACK_REGISTRY` renders the published version (HTML per page) and sends a Teams card + URL. Embedded widgets appear as a placeholder + deep link.
8. **NavigatorWidget:** a parrot catalog component (props `widget_id`, `title`, optional `height`, `param_bindings`). Server-side renderers lower it to a placeholder + deep link. In Navigator, `registerA2uiComponent` mounts `WidgetBox` + `Widget` (as `share/widget/[id]` does) and passes parameters through the `'dashboard'` filter context.
9. **FieldSync:** `ScopedReportBuilderHandler` + `ProgramScopedReportStore`, under `programme_route_prefix()`, behind a flag (like `USE_AGENT_SURFACES`). The `update_envelope(expected_updated_at=)` bug in the surfaces wrapper is fixed here too.

### Edge Cases & Error Handling

- **Concurrent edits** → 412 with the current version; the editor offers to reload. Agent ops get the same treatment.
- **Invalid op** (props outside the schema, overlap, unknown source, source not allowed by the guard) → 422 with the op index, and the whole batch is rejected.
- **Schema drift** on a source (slug columns changed) → the component shows a "data_stage" notice and keeps its snapshot (the FEAT-598 lane does this today). Publishing is blocked if a source fails validation.
- **Empty results** (`DataNotFound`) → an empty component with a notice, not a 502 (known FEAT-611 gap: decide on the mapping).
- **Parameter with no binding** in a source → ignored with a warning (`ignored_params`, as `/refresh` does).
- **NavigatorWidget** that is deleted or has no permission → placeholder "widget not available".
- **Template instantiated** with required parameters missing → 422.
- **Token revoked/expired** → 404 (same as surfaces).
- **Scheduled delivery** with a failing source → send with a notice of the failed sources, or skip per the policy chosen at schedule time.
- **Mobile** → viewer only; the editor route redirects to the viewer.

---

## Capabilities

### New Capabilities
- `report-builder-model`: `Report`/`ReportVersion` model + Pg store (navigator schema), versions and publish/promote.
- `report-builder-operations`: semantic ops endpoint + `If-Match`, with validation by catalog/JSON Schema/layout/guard.
- `report-builder-catalog`: palette endpoint (from `export_catalog_definition`, with `linkable` and props schemas).
- `report-builder-parameters`: typed global parameters, binding to linked sources, propagation on refresh.
- `report-builder-templates`: `kind=template`, gallery, `from_template`, save-as-template.
- `report-builder-share`: visibility + share tokens, reusing the `ui_surfaces` semantics.
- `report-builder-delivery`: `RunReportCallback` + schedules + Teams card + URL.
- `report-builder-render`: per-page HTML render of the published version; placeholder for NavigatorWidget.
- `report-builder-toolkit`: `ReportBuilderToolkit` (absorbs the Dashboard Builder) + "add to report" from AgentTalk.
- `navigator-widget-component`: A2UI `NavigatorWidget` component (parrot catalog + server lowering).
- `fieldsync-report-builder-lane` (fieldsync repo): scoped handler + store + setup + flag; fix the `update_envelope` wrapper.
- `navigator-report-builder-ui` (navigator-svelte): builder route, `GridCanvas` extracted from `Dashboard.svelte`, palette, inspector, parameters, toolbar, viewer, `share/report`.
- `navigator-linked-lane` (navigator-svelte): port of parrot's `a2ui/linked/*` + parity fixtures.

### Modified Capabilities
- `a2ui-linked-surfaces` (FEAT-598): report-level parameters → per-source `ParamSpec`; possible fix for flat MultiQS conditions.
- `a2ui-catalog`: new `NavigatorWidget` component; optional prop validation against JSON Schema in `validate_envelope`.
- `ui-surfaces` (FEAT-492/535): reuse of the share/visibility semantics (FK or extraction into a shared module).
- `interactive-html-renderer`: alignment with ECharts (pending decision).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/` | extends | new handler `report_builder.py` + routes in `manager.py`; distinct segment (not `/api/v1/reports`) |
| `packages/ai-parrot-server/src/parrot/handlers/models/` | extends | `Report`/`ReportVersion` models + Pg store + migration (`navigator` schema) |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/` | extends / modifies | `NavigatorWidget`; catalog route; JSON Schema validation of props |
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/` | modifies | global parameters → sources; MultiQS propagation |
| `packages/ai-parrot-visualizations/.../a2ui_renderers/` | modifies | NavigatorWidget lowering; ECharts alignment (OQ) |
| `packages/ai-parrot-tools/src/parrot_tools/` | extends | `ReportBuilderToolkit` (reuses `qs_build_linked_*`) |
| Scheduler (`CALLBACK_REGISTRY`) | extends | `RunReportCallback` |
| `bots/base.py` / AgentTalk | depends on | "add to report" from a linked surface already lifted (FEAT-611) |
| fieldsync repo | extends / fixes | scoped lane + `update_envelope(expected_updated_at=)` fix |
| navigator-svelte | extends | builder route, GridCanvas, palette, inspector, linked lane, NavigatorWidget renderer, `share/report` |
| `parrot-formdesigner` | depends on (pattern) | versions/ops/toolkit/palette design is copied; no changes to the package |

---

---

## Parallelism Assessment

- **Internal parallelism**: high, and spread across 3 repos.
  - **ai-parrot**:
    - catalog route + `NavigatorWidget` + JSON Schema validation (independent);
    - model/store/versions (base for the rest);
    - ops endpoint + toolkit (depends on the model);
    - parameters in linked (independent of the model until binding);
    - delivery callback (depends on the model + render).
  - **fieldsync**: the lane depends on the parrot handler/store being published as a wheel. The `update_envelope` fix is independent and can ship right away.
  - **navigator-svelte**:
    - linked lane port and `GridCanvas` extraction are independent of the backend;
    - builder UI depends on the catalog + ops endpoints;
    - `NavigatorWidget` renderer depends only on the agreed props schema.
- **Cross-feature independence**:
  - FEAT-623 `infographic-a2ui-display-hints` (IDs reserved, no spec yet) touches A2UI infographic; it shouldn't touch `catalog/__init__.py` or the linked lane, but check this when it lands.
  - FEAT-610/611 (linked e2e) are already merged.
  - The agentstudio specs (FEAT-621/622/605-v0.2) set the FieldSync private/programme/group sharing pattern and should be aligned with.
  - Navigator: FEAT-560/566/613 (reporting) share files (`src/lib/api/a2ui.ts`, reporting routes).
- **Recommended isolation**: **mixed**. Split it into several specs per repo and capability:
  - parrot core (model + ops + catalog);
  - parrot data and delivery;
  - fieldsync lane;
  - navigator linked lane + GridCanvas;
  - navigator builder UI.

  Inside each spec, the tasks with no shared files run in parallel.
- **Rationale**: the work crosses 3 repos with separate lifecycles (parrot wheel → FieldSync → Navigator). One single spec would block parallelism, and the backend/front contracts (ops, catalog, definition schema) can be frozen early in the parrot core spec.

---

## Open Questions

- [x] v1 scope — *Owner: Javier*: interactive board (pages of A2UI components on a 12-column grid, live data, filters, refresh, HTML/PNG export); paginated PDF in phase 2.
- [x] Persistence plane — *Owner: Javier*: ai-parrot, next to `ui_surfaces`, consumed by Navigator through FieldSync (an in-process scoped lane, like surfaces).
- [x] Authoring — *Owner: Javier*: visual editor + agent over a single operations API.
- [x] Native Navigator widgets — *Owner: Javier*: yes, as an embedded `NavigatorWidget` component; in server export, a placeholder with a deep link.
- [x] Filters/parameters — *Owner: Javier*: typed global parameters bound to sources.
- [x] SuperUserToolbar Dashboard Builder — *Owner: Javier*: absorbed into the `ReportBuilderToolkit` (it was only a front-end stub, now deleted).
- [x] v1 must-haves — *Owner: Javier*: versions + publish, templates, share + visibility, scheduled delivery.
- [x] Charting engine — *Owner: Javier*: ECharts only.
- [ ] ECharts vs Chart.js on the server: `InteractiveHTMLRenderer` uses vendored Chart.js and `EChartsRenderer` emits only the first chart. For HTML export and delivery: migrate the server renderer to ECharts in v1, or accept Chart.js in server export while the editor and viewer use ECharts? — *Owner: Javier*
- [ ] API segment: `/api/v1/report-builder/…` vs `/api/v1/boards/…` (`/api/v1/reports/*` is already taken in FieldSync by FEAT-308) — *Owner: Javier / Jesús*
- [ ] Share tokens and visibility: a separate `report_shares` table, or reuse `ui_surface_shares` with a polymorphic FK? — *Owner: backend*
- [ ] Global parameters with multiquery sources: fix the propagation of flat conditions in MultiQS (querysource) or require pinned child conditions? — *Owner: Jesús (querysource)*
- [ ] Empty data (`DataNotFound`) in linked sources: map it to empty rows for the builder, or keep the 502 `data_stage`? (open since FEAT-611 Q2) — *Owner: Javier / Jesús*
- [ ] Client PNG export: html2canvas (already in Navigator) vs a headless server render (Playwright exists only in `parrot_tools/computer`)? — *Owner: front-end*
- [ ] Templates: migrate the infographic templates/themes (in-memory registries) into the new model in this effort, or later? — *Owner: Javier*
- [ ] Scheduled delivery: reuse the FEAT-511 NavAPI wrapper (today keyed by module) or a new endpoint per report? — *Owner: navigator team*
- [ ] Viewer for anonymous users through a token: same rule as surfaces (refresh runs as the owner)? Any additional limits (rate limit, parameters locked)? — *Owner: security*

---

## Code Context

> Verified by reading source on **ai-parrot dev `f01a600f1`**, **navigator-svelte dev `8c34c8d26`** and **fieldsync `9254d2ed`** (2026-10-01). The two blocks below are the verified context, kept whole so `/sdd-spec` can carry it into the Codebase Contract. They include signatures with `file:line` and the "Does NOT Exist" lists.

### User-Provided Code

None. The decisions above come from the discovery rounds.

### Verified Codebase References — ai-parrot



Verified on `dev` @ `f01a600f1` (2026-10-01), read-only. Paths are relative to `packages/`.
`S` = `ai-parrot-server/src/parrot`, `C` = `ai-parrot/src/parrot`, `V` = `ai-parrot-visualizations/src/parrot`, `T` = `ai-parrot-tools/src/parrot_tools`, `FD` = `parrot-formdesigner/src/parrot_formdesigner`.

#### 0. Delta since the inventory (dc3e3a548 → f01a600f1, 347 commits)

- **No code change to A2UI, surfaces, linked, catalog, renderers, infographic or recipes.** The only file in the A2UI tree that changed is the test `tests/.../a2ui/linked/test_seed_staging_guard.py` (FEAT-611 policy fix for navigator-auth 0.28.3, `a283d4f62`). The inventory's code facts still hold.
- Most of the 347 commits are unrelated work: Odoo toolkit (FEAT-616), planogram refactor (FEAT-612), bookstore reindex (FEAT-615), test-bot cleanup (FEAT-617), wheel layout (FEAT-618) and sdd-worktree (FEAT-619).
- parrot-formdesigner had small changes (file_upload, blob_storage, thumbnail and a version bump). None of them touch versions or operations.
- **New specs, no code yet:**
  - **FEAT-623 `infographic-a2ui-display-hints`**: the ID and 9 task IDs are reserved in `sdd/tasks/.id_ledger.json` (`7ad253528`, `f01a600f1`), but no spec file is in the tree yet. Watch it, because it may touch catalog components and hints.
  - **FEAT-621 `agentstudio-db-storage`** (`navigator.ai_agents` + child tables), **FEAT-622 `agentstudio-host-toolkits`** and the revised **FEAT-605 `agentstudio-tenant-visibility` v0.2**. Plan: `sdd/proposals/agentstudio-host-integration.plan.md`. This is the precedent for FieldSync multi-tenant sharing (private / programme / groups), which matches the report share model.

#### 1. ui_surfaces plane (FEAT-492 / 535 / 598)

**Routes**: `S/manager/manager.py:2339-2343`. All of them map to `UISurfacesHandler`.

| Verb + path | Handler method | Notes |
|---|---|---|
| `GET /api/v1/ui/surfaces[?kind=]` | `_get_list` (ui_surfaces.py:466) | `list_visible(scope)` ∪ `list_shared_with(user)`. Each item is tagged `access`: owner, tenant or shared. |
| `GET /api/v1/ui/surfaces/{surface_id}[?share=&format=html\|json]` | `_get_one` (:457) | Negotiated: JSON envelope + metadata, or on-the-fly `InteractiveHTMLRenderer` HTML |
| `POST /api/v1/ui/surfaces` | `_pin_save` (:508) | Body `PublishSurfaceRequest`. Exactly one of `envelope` or `source_artifact_id`. Linked envelopes go through `validate_for_persistence` and then `ensure_snapshot`. Returns 201 `{surface_id}`. |
| `POST .../{surface_id}/refresh` | `_refresh` (:617) → `_refresh_linked` (:688) | Recipe replay (`RecipeRunner.run`) or a linked refresh. Linked refresh persists with `expected_updated_at` and returns **409 "stale refresh"** if it lost the race. Warnings go in the `X-Parrot-Refresh-Warnings` header. |
| `PATCH .../{surface_id}` | `_patch_visibility` (:738) | **Visibility and groups ONLY** (`PatchVisibilityRequest`). Owner-only. |
| `POST .../{surface_id}/share` | `_mint_share` (:787) | `MintShareRequest{expires_at?, ttl: bool}` returns 201 `{token, expires_at, permissions}` |
| `DELETE .../{surface_id}` / `.../share/{token}` | `_delete_surface` (:821) / `_revoke_share` (:830) | owner-only |
| Mirror: `GET /api/v1/agents/{agent_id}/a2ui/surfaces/{surface_id}` | `A2UIHandler._get_surface` (`S/handlers/a2ui.py:266`) | Same `SurfaceNegotiationService` + `resolve_surface_access` |

- **No `put` method, and PATCH does not change the envelope.** The only envelope writer is the refresh path (`store.update_envelope`). Re-publishing creates a new `surface_id`.
- The handler resolves its dependencies from `app[...]`. Each one is created lazily if absent:
  - `app["ui_surfaces_store"]`
  - `app["ui_surfaces_negotiation"]`
  - `app["linked_surface_service"]`: `LinkedSurfaceService(guard=app.get("dataplane_guard"))` (:346)
  - `app["recipe_runner"]`
  - `app["artifact_store"]`
  - `app["ui_surfaces_scope_resolver"]`
- Wire models in `S/handlers/ui_surfaces.py`:
  - `PublishSurfaceRequest` (:69): `kind: UISurfaceKind`, `title: str`, `envelope: dict|None`, `source_artifact_id`, `agent_id`, `session_id`, `recipe_name`, `recipe_owner: str|None`, `recipe_params: dict`, `visibility: SurfaceVisibility = private`, `allowed_groups: list[str]`. There is deliberately no `tenant` field; the server sets it from the scope.
  - `RefreshSurfaceRequest(params: dict)` (:96). `params` is flat: a key that names a source with a dict value overrides only that source; every other key is broadcast to all sources.
  - `MintShareRequest` (:102).
  - `PatchVisibilityRequest(visibility, allowed_groups)` (:109).
- Shared helpers:
  - `async resolve_surface_access(store, surface_id, user_id, token, *, scope=None) -> tuple[UISurfaceRecord|None, tuple[str,int]|None]` (:167). Checks run in this order: owner, then scope (`scope_grants`), then share token (`resolve_share` + `claim_share`). Failures return 404, or 410 for a bad token.
  - `SurfaceNegotiationService.negotiate(request) -> str` (:226). `?format=` wins over `Accept`, and the default is JSON.
  - `async respond(record, accept) -> web.Response` (:249). HTML returns 501 if visualizations is not installed and 422 on a render failure.
- Scope (`S/handlers/ui_surfaces_scope.py`):
  - `@dataclass(frozen) SurfaceScope(user_id: str|None, tenant: str|None, groups: frozenset[str], is_superuser: bool=False)` (:41). `EMPTY_SCOPE` is a constant.
  - `SurfaceScopeResolver` Protocol `async resolve(request) -> SurfaceScope` (:73).
  - `SessionSurfaceScopeResolver` (:86) sets `tenant` only when the session's `programs` list has exactly one entry. **FieldSync must install its own resolver** in `app["ui_surfaces_scope_resolver"]`.
  - `get_scope_resolver(app)` (:149).
  - `scope_grants(record, scope) -> bool` (:171). Same tenant is required, then superuser, `visibility==tenant`, or a group intersection.

**Models and store**: `S/handlers/models/ui_surfaces.py`. Import with `from parrot.handlers.models.ui_surfaces import PgUISurfaceStore, UISurfaceRecord, UISurfaceKind, SurfaceVisibility, UISurfaceShare`.
- `UISurfaceKind(str, Enum)` (:42): `dashboard | infographic | widget`. There is no `report` member.
- `SurfaceVisibility(str, Enum)` (:50): `private | tenant | groups`.
- `UISurfaceRecord(BaseModel)` (:64) has these fields:
  - `surface_id: str`, `kind`, `title`, `envelope: dict`, `catalog_id: str|None`, `agent_id: str`, `user_id: str`, `session_id`
  - `recipe_name`, `recipe_owner`, `recipe_params: dict`
  - `tenant: str|None`, `visibility`, `allowed_groups: list[str]`
  - `created_at`, `updated_at: datetime`
  - Property `refreshable` (:85) is `recipe_name is not None or has_data_sources(envelope)`.
- `UISurfaceShare` (:90): `token`, `surface_id`, `permissions: Literal["read+refresh"]`, `expires_at`, `revoked`, `claimed_by`, `claimed_at`, `created_at`.
- DDL `_DDL_STATEMENTS` (:107-154) is auto-created and idempotent.
  - `navigator.ui_surfaces(surface_id UUID PK, kind VARCHAR(32), title TEXT, envelope JSONB, catalog_id, agent_id NOT NULL, user_id NOT NULL, session_id, recipe_name, recipe_owner, recipe_params JSONB, tenant VARCHAR(63), visibility VARCHAR(16) DEFAULT 'private', allowed_groups JSONB DEFAULT '[]', created_at, updated_at TIMESTAMPTZ)`
  - Indexes on (user_id), (user_id, kind) and (tenant, visibility).
  - `navigator.ui_surface_shares(token TEXT PK, surface_id UUID FK ON DELETE CASCADE, permissions DEFAULT 'read+refresh', expires_at, revoked, claimed_by, claimed_at, created_at)`
  - Migrations use `ADD COLUMN IF NOT EXISTS` (the bots.py idiom).
- `class PgUISurfaceStore` (:457):
  - `__init__(dsn: str|None=None)` with `DEFAULT_SHARE_TTL_DAYS = 90`.
  - Each call does `AsyncDB("pg", dsn)`. `ensure_schema()` (:483) runs lazily.
  - Methods:
    - `async save(record, *, overwrite=False) -> str` (:503). An insert that skips on conflict raises `ValueError` on a duplicate; `overwrite=True` upserts.
    - `async get(surface_id) -> UISurfaceRecord|None` (:553)
    - `async list(user_id, *, kind=None) -> list[UISurfaceRecord]` (:564)
    - `async list_shared_with(user_id) -> list` (:575)
    - `async list_visible(scope, *, kind=None) -> list` (:583)
    - `async update_visibility(surface_id, user_id, visibility, allowed_groups) -> bool` (:624)
    - `async update_envelope(surface_id, envelope: dict, recipe_params: dict, *, expected_updated_at: datetime|None=None) -> bool` (:656). This is the optimistic-concurrency path (FEAT-598 S11).
    - `async delete(surface_id, user_id) -> bool` (:686)
    - `async mint_share(surface_id, *, expires_at=None, use_default_ttl=False) -> UISurfaceShare` (:697). The token is `secrets.token_urlsafe(32)`.
    - `async resolve_share(token) -> UISurfaceShare|None` (:733)
    - `async claim_share(token, user_id) -> None` (:745). The first claimant wins.
    - `async revoke_share(token, surface_id) -> bool` (:757)
    - `async list_shares(surface_id) -> list[UISurfaceShare]` (:768). The store has this method, but **no HTTP route exposes it**.
  - asyncdb gotchas (documented at :395-416): writes go through `fetchval ... RETURNING`; UUIDs must be passed as `uuid.UUID`; JSONB values must be passed as raw dicts, never `json.dumps`.
- **Share token flow**:
  1. The owner calls `POST /share`, which returns an opaque DB token (no signature and no JWT).
  2. A viewer opens `GET /{id}?share=<token>` or `POST /{id}/refresh?share=<token>`. The token check comes after the owner and scope checks.
  3. An authenticated viewer is recorded as the claimant, and the surface then appears in that viewer's shared-with-me list.
  4. Refresh always runs with the **owner's** `build_principal_context(record.user_id, channel="ui_surfaces")`.
  5. Revoked or expired tokens return 410.
  6. **There is no signed-URL primitive.** A scheduled-delivery link would reuse a share token with a TTL.

#### 2. Linked surfaces (FEAT-598): service, executor, models, builders, validation, catalog

- `from parrot.outputs.a2ui.linked import LinkedDataSource, LinkedSources, ParamSpec, SourceRequest, RefreshPolicy, TransformSpec, has_data_sources, DATA_SOURCES_EXTENSION`. The execution-side names are lazy-loaded (PEP 562, `C/outputs/a2ui/linked/__init__.py:37-52`): `execute_sources`, `LinkedSurfaceService`, `LinkedGuardRequired` and others.
- `DATA_SOURCES_EXTENSION = "parrot_data_sources"`. Sources live in `createSurface.metadata.extensions.parrot_data_sources`, keyed by the dataModel root key. Rows land in `dataModel[<key>].rows`.
- Models (`C/outputs/a2ui/linked/models.py`). All use `extra="forbid"`.
  - `ParamSpec` (:19): `type: str|None`, `default: Any`, `required=False`, `editable=True`, `accepts_keywords=False`. Parameters are declared **per source**; there is no surface-level or global parameter.
  - `SourceRequest` (:30): `placeholders: dict`, `filter: dict`, `fields: list[str]`, `ordering`, `grouping: list[str]`, `limit`, `offset: int|None`.
  - `RefreshPolicy` (:43): `policy: Literal["on_mount","manual","interval"]="on_mount"`, `interval_seconds: int|None`. The minimum interval is 30 s (`MIN_INTERVAL_SECONDS`).
  - `TransformSpec` (:178) holds exactly one of `ops: list[TransformOp]` or `ref: TransformRef(name="x@1.2.3", integrity="sha384-…")`.
    - Ops (a discriminated union on `op`): `select`, `rename`, `filter` (eq/ne/gt/ge/lt/le/in/contains), `group_by`, `sort`, `limit`, `derive`, `pivot`, `join(with, how, on)` and `union(sources)`.
  - `LinkedDataSource` (:192):
    - `kind: Literal["query_slug"]`, `slug: str`, `tenant: str|None`, `is_multiquery: bool`, `multi_output: str|None`
    - `conditions: dict`, `request: SourceRequest`, `params: dict[str, ParamSpec]`, `locked: list[str]`
    - `transform: TransformSpec|None`, `target: str` (an absolute JSON pointer)
    - `snapshot_at: datetime|None`, `snapshot_truncated: bool`, `refresh: RefreshPolicy`
  - `LinkedSources(RootModel[dict[str, LinkedDataSource]])` (:226). Each key must equal the target's root token.
- `C/outputs/a2ui/linked/service.py`:
  - `LinkedGuardRequired(Exception)` (:31) maps to HTTP 403.
  - `SnapshotError(status: int, code: str)` (:35).
  - `RefreshOutcome(BaseModel)` (:44): `envelope: dict`, `snapshot_at`, `warnings: list[str]`, `error_status: int|None`, `error_code`.
  - `class LinkedSurfaceService` (:67). It **fails closed** without a guard.
    - `__init__(*, guard: Any|None, max_fetch_rows: int=5000, max_snapshot_rows: int=500)`
    - `async validate_for_persistence(envelope: CreateSurface, *, owner_pctx: PermissionContext) -> None` (:109) runs a TOOL-origin `validate_envelope` plus a per-source `guard.authorize_source(owner_pctx, PhysicalResources(source_type="query_slug", source_id=f"{tenant or 'public'}:{slug}"))`.
    - `async ensure_snapshot(envelope: dict, *, owner_pctx) -> dict` (:119)
    - `async refresh(envelope: dict, *, params: Mapping, owner_pctx) -> RefreshOutcome` (:152). It never persists; the caller does.
- `C/outputs/a2ui/linked/executor.py`:
  - `async execute_sources(sources: Mapping[str, LinkedDataSource], *, param_overrides: Mapping[str, Mapping]|None=None, pctx=None, guard=None, max_snapshot_rows: int|None=None, max_fetch_rows: int=5000) -> ExecutionOutcome` (:180).
    - It wraps `QuerySlugSource` in `AuthorizingDataSource`.
    - Sibling sources run first (join and union dependencies).
    - Failures are isolated per source.
  - `SourceOutcome` (:45): `key`, `rows`, `snapshot_at`, `truncated`, `error`, `ignored_params`.
  - `ExecutionOutcome` (:56): `outcomes: dict[str, SourceOutcome]`, `frames` (in-process DataFrames), and `.data_model_patch()`.
  - `map_query_error(exc) -> (status, code)` (:71). The `ERROR_STATUS` code table sits near the top of the file (around :25-31).
- Builders (`C/outputs/a2ui/builders.py`):
  - `build_linked_surface(components: Sequence[dict], sources: Mapping[str, LinkedDataSource], frames: Mapping[str, pd.DataFrame], *, surface_id: str, snapshot: bool=True, max_snapshot_rows: int=500, catalog_id: str=DEFAULT_CATALOG_ID) -> CreateSurface` (:513). It validates axes against the frames, stamps snapshots, and validates the result as TOOL origin.
  - `build_surface(component, properties, *, surface_id, component_id="root", data_model=None, origin=ProducerOrigin.LLM, metadata=None, surface_metadata=None) -> CreateSurface` (:77).
  - Per-type helpers: `build_chart` :128, `build_kpicard` :149, `build_card` :169, `build_datatable` :191, `build_map` :215, `build_infographic` :247, `build_html_document` :276, `build_graph` :328.
- Envelope model (`C/outputs/a2ui/models.py`):
  - `CreateSurface(surfaceId, catalogId, sendDataModel=False, components: list[Component], dataModel: dict, metadata: SurfaceMetadata|None)` (:446, `extra="forbid"`).
  - `Component(id, component, catalogId?, child?, children?, weight?, accessibility?, checks?, action?, metadata?)` (:400, `extra="allow"`). Props sit at the top level of the component. The tree is a flat adjacency list: exactly one `id=="root"`, with links via `child`/`children`.
  - `SurfaceMetadata = ComponentMetadata(extensions: Extensions|None)` (:364). The `a2ui_` prefix is reserved for extensions.
- Validation (`C/outputs/a2ui/catalog/__init__.py`):
  - `validate_envelope(envelope: CreateSurface|UpdateComponents, *, origin: ProducerOrigin=TOOL, surface_catalog_id=None) -> None` (:689). It raises `CatalogValidationError(.issues)` with every problem found.
    - Structure: root present, no duplicate ids, no dangling children, allowed_parents and allowed_children respected.
    - LLM-origin gates: no actions, no inline data, no tool_only components, no data sources.
    - Linked sources: `_validate_linked_sources` (:580) and `_validate_filter_params` (:521). The FilterBar param must name a declared source and param.
  - `ProducerOrigin(str, Enum)`: `TOOL | LLM` (`catalog/base.py:99`).
- Catalog registry (`C/outputs/a2ui/catalog/__init__.py`):
  - The registry is `_CATALOG: dict[(catalog_id, name), RegisteredComponent]` (:101).
  - `register_component(name, *, requires_actions=False, catalog_id=DEFAULT_CATALOG_ID, is_primitive=False, allowed_parents=None, allowed_children=None, tool_only=False) -> Callable[[type], type]` (:114).
    - The class must define `lower(self, component, data_model) -> BasicTree`, unless it is a primitive.
    - `schema` and `instructions` are read from the class attributes `SCHEMA` and `INSTRUCTIONS`.
  - Other functions: `unregister_component` :196, `get_component(name, catalog_id=None) -> RegisteredComponent` :209, `list_components(catalog_id=None) -> list[ComponentDefinition]` :253, `catalog_instructions(catalog_ids=None) -> str` :314, `resolve_catalog` :345.
  - `ComponentDefinition(BaseModel)` (`catalog/base.py:234`): `name`, `catalog_id`, `schema_` (alias `schema`), `instructions: str`, `requires_actions`, `is_primitive`, `allowed_parents`, `allowed_children: list[str]|None`, `tool_only: bool`. **There is no `linkable`/`bindable` flag** (searched; absent).
  - Catalog ids:
    - `DEFAULT_CATALOG_ID = "https://parrot.dev/catalogs/v1"` (base.py:53)
    - `BASIC_CATALOG_ID = "https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json"` (basic/__init__.py:44)
    - `VIZ_CORE_CATALOG_ID = "https://ai-parrot.dev/a2ui/catalogs/viz-core/1.0/catalog.json"` (viz_core/__init__.py:28)
- Export (`C/outputs/a2ui/catalog/export.py`):
  - `export_catalog_definition(*, catalog_id=DEFAULT_CATALOG_ID, include_basic: bool=True, executor: FunctionExecutor|None=None) -> dict` (:215). It returns `protocolVersion`, `catalogId`, `instructions`, `components` and `functions`.
  - `write_catalog_definition(path, *, catalog_id)` (:299).
  - `agent_capabilities(catalog_ids: list[str]) -> dict` (:195) returns `{"v1.0": {"supportedCatalogIds": [...], "acceptsInlineCatalogs": False}}`.
- **Capabilities route**: `GET /api/v1/agents/{agent_id}/a2ui/capabilities` (manager.py:2326) → `A2UIHandler._get_capabilities` (`S/handlers/a2ui.py:240`). It returns only `agent_capabilities([DEFAULT, BASIC])`, which is the list of catalog ids and **not the catalog definition**. `export_catalog_definition` has no HTTP route; it is used only for the Agent Card (`S/a2a/server.py:179` `register_a2ui_extension`) and the vendored spec files.

#### 3. Parrot catalog components (today)

| Catalog | Component | Module (`C/outputs/a2ui/catalog/…`) | Flags |
|---|---|---|---|
| parrot (`DEFAULT`) | Chart | parrot/chart.py:54 | — |
| | DataTable | parrot/datatable.py:51 | — |
| | KPICard | parrot/kpicard.py:118 | — |
| | InfoCard | parrot/infocard.py:37 | — |
| | Map | parrot/map.py:71 | — |
| | Timeline | parrot/timeline.py:43 | — |
| | FilterBar | parrot/filterbar.py:127 | Lowers to a Row of ChoicePickers carrying `parrot_role:"filter"` and an optional `parrot_param{source,name}` |
| | Report | parrot/report.py:110 | `allowed_parents=["root","Column"]`. Schema: `title`, `reportMetadata`, `summary`, `sections[{heading, text, components[{component, properties}]}]` (single-column narrative) |
| | Infographic | parrot/infographic.py:203 | `allowed_parents=["root","Column"]`. Blocks pair up into a Row using `parrot_layout:"half"` |
| | HtmlDocument | parrot/htmldocument.py:60 | `tool_only=True` |
| viz-core | Graph | viz_core/graph.py:63 | — |
| basic (18 primitives) | Text, Image, Icon, Video, AudioPlayer, Row, Column, List, Card, Tabs, Modal, Divider, Button, TextField, CheckBox, ChoicePicker, Slider, DateTimeInput | basic/__init__.py:182-202 | `is_primitive=True` |

- `Form` is retired as a component; `build_form()` composes Basic primitives instead (parrot/__init__.py docstring and parrot/form.py).
- **No Page, Dashboard, Grid or Board container exists.** A search for `"Page"`, `"Dashboard"`, `"Grid"`, `colSpan` and `gridColumn` found nothing in outputs, visualizations or tools. The only layout knob is surface-level `metadata.extensions.parrot_layout`, which takes one of `{"report","analytics","print"}` (default `analytics`), via `DesignSystem.LAYOUTS` (`V/outputs/formats/assets/design_system/__init__.py:99`). The 12-column grid and pages will need a new component, an extension, or both.

#### 4. parrot-formdesigner: the pattern to copy (versions, operations with If-Match, toolkit, palette)

**Corrections to the brief:**
- **No ETag is ever emitted.** `If-Match` is **optional** and is compared to the plain `form.version` string.
- Nothing in the package returns 428.
- Routes are tenant-scoped: `/api/v1/{tenant}/forms/...`.
- **There is no separate versions table.** Versions are rows of the same table.

- **Storage**: `FD/services/storage.py` `PostgresFormStorage(FormStorage)` (:69). Its table is `navigator.form_schemas` (DDL at :159-176):

  ```
  id UUID PK, form_uid UUID, form_id VARCHAR(255), version VARCHAR(50) DEFAULT '1.0',
  schema_json JSONB, style_json JSONB, tenant VARCHAR(63), created_at, updated_at, created_by,
  UNIQUE(form_uid, version), UNIQUE(tenant, form_id, version)
  ```

  - `save(form, style=None, *, created_by=None, tenant=None) -> str` (:395) upserts `ON CONFLICT (form_uid, version)`.
  - `promote(form_uid: UUID, version: str, schema_json: str, *, tenant=None) -> bool` (:447) uses `DO UPDATE … WHERE schema_json->>'published_version' IS DISTINCT FROM version`.
  - `list_versions(form_uid, *, tenant=None) -> list[dict]` (:703).
- **Version service**: `FD/services/form_version.py`. Import with `from parrot_formdesigner.services.form_version import FormVersionService, VersionMeta`.
  - `VersionMeta` (:35): `form_id`, `version`, `published_at`, `tenant`, `is_published`, `is_frozen`.
  - `FormVersionService(registry: FormRegistry, storage: FormStorage|None=None, *, has_responses: Callable[[str,str], Awaitable[bool]]|None=None)` (:251/:283).
  - Methods:
    - `async publish(form_uid, *, tenant: str, bump: str="minor") -> str` (:306). Promotes the current version in place. Raises `KeyError` (form missing) or `ValueError` (already published).
    - `async get_published(form_uid, *, version, tenant) -> FormSchema|None` (:431)
    - `async list_versions(form_uid, *, tenant) -> list[VersionMeta]` (:480)
    - `can_delete` (:572), `safe_delete` (:590), `backfill_published` (:610)
  - There is no status enum. "Published" means `schema_json.published_version == version`. Every save or operations PATCH bumps the minor version and writes a new draft row (`api/_utils._bump_version`, :61).
- **Operations endpoint**: `FD/api/operations.py`. `async handle_operations(request) -> web.Response` (:521) serves `PATCH {bp}/{tenant}/forms/{form_uid}/operations` (routes.py:432).
  - Processing order:
    1. `If-Match` check (:561-574). A mismatch returns **412** `{"detail":"version mismatch","current":…}`.
    2. Apply the ops in order on a deep copy. Bad JSON returns 400; a bad envelope or a failing op returns 422 `{"errors":[{index, op, message}]}`.
    3. `resolve_rule_references`, then `FormValidator().check_schema`.
    4. Bump the version and call `registry.register(..., persist=True, overwrite=True)`.
    5. Return 200 `{"form": …}`.
  - Op models:
    - `OperationsEnvelope(operations: list[Operation])` (:183), with `extra="forbid"`.
    - `Operation` (:177) is a union discriminated on `op` over `AddSection`, `AddField`, `MoveField`, `RemoveField`, `UpdateField`, `UpdateSectionMeta`, `UpdateFormMeta` and `DuplicateField`. Fields such as `section_uid`, `field_uid`, `position`, `from`/`to` and `patch` (RFC 7396).
  - Each op is applied by an `_apply_<op>(form, op) -> FormSchema` function (:327-501), looked up in the `_DISPATCH` dict (:504).
  - `OperationError(index, op_name, message)` (:196).
- **EditToolkit**: `from parrot_formdesigner.tools import EditToolkit` (`FD/tools/edit_toolkit.py:63`), a subclass of `AbstractToolkit`.
  - `__init__(form: FormSchema, **kw)` works on a deep copy. It **reuses the same `_apply_*` functions** as the HTTP operations; this is the "one operations API" precedent.
  - It does no persistence, versioning or If-Match. The caller reads `.form`; `is_done` tells it when to stop.
  - Tools:
    - Inspection: `get_form_summary`, `get_section`, `get_field`, `search_fields`
    - Field edits: `update_field`, `add_field`, `add_field_from_schema`, `remove_field`, `move_field`
    - Dependencies: `add_dependency`, `update_dependency`, `remove_dependency`, `add_post_dependency`, `remove_post_dependency`
    - Sections: `add_section`, `add_section_from_schema`, `update_section`, `update_section_title`
    - Form: `update_form_meta`, `update_form_title`, `update_form_description`
    - Control: `done`
  - There is no `duplicate_field` tool.
- **Palette**: `FD/api/controls.py:20` `async handle_form_controls(request)` serves `GET {bp}/form-controls` (no tenant). It returns `{"controls":[FieldControlMetadata…]}`.
  - The data comes from an in-memory registry `FD/controls/registry.py`: `_REGISTRY` (:91), `register_field_control(field_type, *, label, description, category, icon, snippet, render_hint, supports_constraints, is_container=False, supported_operators=None, …)` (:94) and `get_controls()` (:156).
  - `FieldControlMetadata` (:36) fields: `type`, `label`, `description`, `category`, `icon`, `snippet: dict`, `render_hint`, `supports_constraints`, `is_container`, `supported_operators`, `supported_effects`, `supported_operations`, `value_shape`.
  - Built-ins are seeded by `controls/builtin.py` `_seed()` (:624).
  - **Report-builder analog:** a `/api/v1/report-components` palette fed from `list_components()` plus a per-component "palette" metadata layer.
- **Publish and versions HTTP**: `FormAPIHandler` (`FD/api/handlers.py:110`).
  - `POST …/publish` (:2116) returns 200, 404 or 409.
  - `GET …/versions` (:2187) returns `{versions:[{version, published_at, is_current, is_published}]}`.
  - `GET …/versions/{version}` (:2237).
- Route registration: `setup_form_api(app, registry, *, base_path="/api/v1", …)` (`FD/api/routes.py:192`). Each handler is wrapped in `_wrap_auth(handler, tenant="required"|"public"|"none")` (:84).

#### 5. Scheduler and delivery

- **Table** `navigator.agents_scheduler`. Model: `parrot.scheduler.models.AgentSchedule` (asyncdb Model; the DDL is in its docstring at `S/scheduler/models.py:12-36`). Columns:
  - `schedule_id UUID PK`, `agent_id`, `agent_name`, `prompt`, `method_name`
  - `schedule_type`, `schedule_config JSONB`, `enabled`
  - `created_by INT`, `created_email`, `created_at`, `updated_at`, `last_run`, `next_run`, `run_count`
  - `metadata JSONB`, `send_result JSONB`, `is_crew`, `scheduler_type`
  - `callbacks JSONB DEFAULT '[]'`
- `ScheduleType` (`S/scheduler/manager.py:62`): `once | daily | weekly | monthly | interval | cron | crontab`. `_create_trigger` (:920) maps them to APScheduler triggers.
- `AgentSchedulerManager(bot_manager=None, **kw)` (:325) lives in `app["scheduler_manager"]`.
  - `add_schedule(agent_name, schedule_type, schedule_config, prompt=None, method_name=None, created_by=None, created_email=None, metadata=None, agent_id=None, *, is_crew=False, send_result=None, success_callback=None, scheduler_type="default", callbacks: list[dict]|None=None) -> AgentSchedule` (:975).
  - Routes: `/api/v1/parrot/scheduler/schedules[/{id}]`, `…/{id}/last-result`, `/api/v1/parrot/scheduler/callbacks` and `…/restart` (:1818-1827).
  - **Every job is an agent job.** `_execute_agent_job` (:609) needs `bot_manager`, and callbacks run only after the agent succeeds (`_handle_job_success`, :704). There is no "report job" type; a report delivery would be an agent job with a no-op or `method_name` step plus a callback, or a new scheduler type.
- **Callback registry**: `parrot.scheduler.functions` (`S/scheduler/functions/__init__.py`).
  - `BaseSchedulerCallback(NotificationMixin)` (:16) has the class attributes `callback_name` and `description`, plus `__init__(config: dict|None=None, logger=None)`, `process_output(result)` and `async run(self, result, *, schedule_id: str, agent_name: str, **kw) -> dict`.
  - `CALLBACK_REGISTRY: dict[str, type]` (:195) is a plain dict and is extended by assignment.
  - `build_scheduler_callback(definition: {"type"|"name", "config"}, logger=None)` (:210) and `list_supported_callbacks()` (:206).
  - Built-ins: `send_email_report`, `create_file`, `save_data`, `send_notify_report` (Telegram, Teams or Slack).
- **`RunInfographicRecipeCallback`** (`S/handlers/infographic_recipes.py:323`). `callback_name="run_infographic_recipe"`; config is `{recipe_name, params?}`.
  - It self-registers as an import side effect (`CALLBACK_REGISTRY[...] = …`, :388), triggered by manager.py importing `RecipeHandler`.
  - It runs `get_recipe_runner().run(...)` as `recipe.schedule.principal` (`ScheduleSpec(principal, tenant_id, roles)`, `C/outputs/a2ui/recipes/models.py:191`).
  - It only finds recipes with owner `''`.
  - **This is the template for a `deliver_report` callback.**
- **Teams card helpers** (no FEAT-430/511 references in src):
  - `parrot.notifications.NotificationMixin` (`C/notifications/__init__.py`):
    - `build_teams_card(title, text="", *, summary=None, sections=None, actions=None, files=None, version="1.5") -> TeamsCard` (:124)
    - `async send_teams_card(message: TeamsCard|dict|str|None=None, recipients=None, report=None, *, card=None, recipient=None, with_attachments=True, provider_options=None, **kw) -> dict` (:1696). It accepts a raw Adaptive Card dict.
    - `send_teams_message` (:1637)
    - `send_notification(message, recipients, provider=EMAIL, …)` (:419)
  - Every scheduler callback inherits this mixin.
  - `parrot.outputs.a2ui.delivery.deliver_artifact(owner, artifact: RenderedArtifact, *, recipients, provider="email", message="", subject=None, artifact_store=None, user_id=None, agent_id=None, session_id=None) -> dict` (`C/outputs/a2ui/delivery.py:86`). For Teams it only adds filenames to the message; real Graph upload is pending (TASK-1734).
  - `AdaptiveCardsRenderer` (`V/outputs/a2ui_renderers/adaptive_cards.py:212-234`, MIME `application/vnd.microsoft.card.adaptive`).
- **Signed URLs**: `ArtifactStore.get_public_url(user_id, agent_id, session_id, artifact_id, *, format="html"|"json") -> str` (`C/storage/artifacts.py:177`) returns an S3 sigv4 presigned URL that lasts at most 7 days. `overflow.generate_presigned_url(key, *, expires_in=604800)` (`C/storage/overflow.py:119`). The surface "share token" (§1) is the other option and has no 7-day cap.

#### 6. Infographic templates, themes and recipes

- **Templates**: in memory only. `parrot.models.infographic_templates.InfographicTemplateRegistry` (:512) has `register(t)`, `get(name)` (raises `KeyError`), `list_templates()` and `list_templates_detailed()`. The singleton is `infographic_registry` (:587), with 9 built-ins.
- **Themes**: in memory only. `parrot.models.infographic.ThemeRegistry` (:1518). The singleton is `theme_registry` (:1580), with 5 built-ins.
- **REST**: `InfographicTalk(AgentTalk)` (`S/handlers/infographic.py:72`), mounted at `manager.py:2430-2461`:
  - `GET|POST /api/v1/agents/infographic/{templates|themes}[/{name}]`. POST needs PBAC `agent:configure`.
  - `POST …/render` (deterministic) and `GET …/render/jobs/{job_id}`.
  - Registrations are per process and not persisted. **Report templates cannot copy this as-is; they need a DB table.**
- **Recipes**: `parrot.handlers.models.recipes.PgRecipeStore(dsn=None, *, schema="navigator")` (`S/handlers/models/recipes.py:128`).
  - `navigator.infographic_recipes(name, owner DEFAULT '', schema_version, title, description, recipe JSONB, created_at, updated_at, PK(name, owner))`.
  - Methods: `save(recipe)`, `get(name, owner=None)`, `list(owner=None) -> list[dict]`, `delete(name, owner=None)`.
- **`register_recipe_routes(app, *, recipe_store, recipe_runner=None, dataset_manager=None, artifact_store=None) -> RecipeRunner`** (`S/handlers/infographic_recipes.py:78`).
  - It **adds no routes**. It only sets `app["recipe_store"]` and `app["recipe_runner"]` and calls `configure_recipe_runner`.
  - **Nothing in ai-parrot calls it outside tests.** It may still be called from a host app; that was not checked.
  - The routes themselves are always mounted (`/api/v1/infographic_recipes[/{name}[/run]]`, manager.py:2496-2498). Until a host wires the store and runner, they return 500 "recipe_store is not configured", the `run_infographic_recipe` callback raises, and recipe-backed surface refresh returns 500.
- `RecipeRunner(store, dataset_manager, *, artifact_store=None, owner=None, narrator=None)` (`C/tools/infographic_recipes/runner.py:205`).
  - `async run(name, *, params=None, pctx=None, recipe_owner=None, include_envelope=False) -> RenderedArtifact` (:243). Stages: params → data → gate → transform → layout → render → delivery.
  - `dry_run(recipe)` (:307).

#### 7. Agent tools

**QuerysourceToolkit**
- Import: `from parrot_tools.querysource.toolkit import QuerysourceToolkit` (`T/querysource/toolkit.py:72`). It subclasses `AbstractToolkit` with `tool_prefix="qs"`.
- Tools:
  - `qs_get_dialect_reference`, `qs_list_slugs`, `qs_describe_slug`, `qs_execute_slug`
  - `qs_build_linked_surface`, `qs_build_linked_dashboard`, `qs_list_components`
  - `qs_validate_pipeline`, `qs_run_multiquery`
  - `qs_save_multiquery`, only when `allow_write=True`
- `async build_linked_surface(self, slug: str, component: dict, request: dict|None=None, tenant: str|None=None, snapshot: bool=True, surface_id: str|None=None, target_key: str|None=None, refresh: dict|None=None, transform: dict|None=None) -> dict` (:347).
  - Pipeline: `describe_slug` → `execute_sources` → `builders.build_linked_surface`.
  - Returns `{"a2ui_envelope": {...}, "artifacts":[{"type":"a2ui_linked_surface", surface_id, sources, slug, tenant}]}`.
- `async build_linked_dashboard(self, widgets: list[dict], surface_id: str|None=None, title: str|None=None, snapshot: bool=True) -> dict` (:407).
  - Each widget is a `DashboardWidget` (`T/querysource/models.py:127`): `key`, `slug`, `component: dict`, `request`, `tenant`, `section: Literal["kpis","charts","table"]|None`, `refresh`.
  - **Layout is fixed** by `_dashboard_layout` (:479): a root Column holding a KPI row, a charts row, then tables. There is no grid and no page concept. This is the closest prior art to a board builder.

**PublishSurfaceTool**
- Import: `from parrot_tools.ui_surfaces import PublishSurfaceTool, PublishSurfaceArgs` (`T/ui_surfaces.py:65`), with `name="publish_surface"`.
- Args (:35): `kind`, `title`, `envelope: dict`, `recipe_name`, `recipe_owner`, `recipe_params`, `overwrite=False`.
- `__init__(bot=None, surface_store=None, agent_id=None, user_id=None, session_id=None, linked_service=None, guard=None, **kw)`.
- It delegates to `bot.publish_surface` when the bound bot has one. Otherwise it writes `PgUISurfaceStore` directly, after running linked validation and the snapshot step.
- Returns `{surface_id, kind, refreshable}`.

**InfographicAuthoringMixin**
- `async publish_surface(self, *, kind: str, title: str, envelope: CreateSurface|dict, recipe_name=None, recipe_owner=None, recipe_params=None, overwrite=False, surface_store=None, user_id=None, session_id=None) -> str` (`C/bots/mixins/infographic_authoring.py:442`; the class is at :58).
- Raises `ValueError`, `RuntimeError`, `LinkedGuardRequired`, `AuthorizationRequired`, `CatalogValidationError` or `SnapshotError`.

**NavigatorToolkit**
- Import: `from parrot_tools.navigator.toolkit import NavigatorToolkit` (`T/navigator/toolkit.py:42`). It subclasses `PostgresToolkit` with `tool_prefix="nav"`.
- Write tools use a `confirm_execution` pending-confirmation flow.
- Dashboard and widget tools:

| Tool | Line |
|---|---|
| `nav_create_dashboard(name, module_id\|module_slug, program_id\|program_slug, description, dashboard_type="3", position, enabled, shared, published, allow_filtering, allow_widgets, params, attributes, conditions, user_id, save_filtering, slug, cond_definition, filtering_show, confirm_execution)` | :1334 |
| `nav_update_dashboard(dashboard_id, confirm_execution, **kw)` | :1448 |
| `nav_get_dashboard` | :1502 |
| `nav_list_dashboards(program_id, module_id, active_only, limit)` | :1523 |
| `nav_publish_dashboard(dashboard_id, confirm_execution)` | :1582 |
| `nav_clone_dashboard(...)` | :1693 |
| `nav_create_widget(dashboard_id\|dashboard_name, program_*, widget_type_id="api-echarts", template_id, widget_name, title, widgetcat_id=3, module_id, url, params, attributes, conditions, format_definition, query_slug: dict, grid_position: dict[str,int], user_id, description, cond_definition, where_definition, embed, confirm_execution)` | :1847 |
| `nav_update_widget` | :1980 |
| `nav_get_widget` | :2062 |
| `nav_list_widgets(dashboard_id, program_id, active_only, limit)` | :2091 |
| `nav_list_widget_types` | :2230 |
| `nav_list_widget_categories` | :2241 |
| `nav_get_widget_schema(widget_type_id)` | :2290 |
| `nav_find_widget_templates(widget_type_id, program_id, limit)` | :2358 |
| `nav_search_widget_docs(query)` | :2392 |

- Module and program tools: `nav_create_module` :946, `nav_update_module`, `nav_get_module`, `nav_list_modules`, `nav_assign_module_to_client`, `nav_assign_module_to_group`, `nav_get_full_program_structure` :2427, `nav_search` :2487.
- `nav_list_widgets` and `nav_get_widget` are the data a `NavigatorWidget` A2UI picker would need (widget uuid, type, dashboard).

**SuperUserToolbar "Dashboard Builder"**
- It does not exist in ai-parrot.
- It was a navigator-svelte front-end stub: `SPEC_SuperUserToolbar.md`, and `AgentDrawer.svelte` posting to `/api/agent/dashboard-builder`.
- `SuperUserToolbar.svelte` was deleted in TASK-2948 (`238286aef`), and the backend endpoint was never built.
- Absorbing it into a ReportBuilderToolkit means writing new code; there is nothing to port.

#### 8. Renderers (`V/outputs/a2ui_renderers/`)

- Every renderer registers through `@register_a2ui_renderer(name, RendererCapabilities)` and is looked up with `get_a2ui_renderer(name)` (`C/outputs/a2ui/renderers/__init__.py:108/:141`).
- All of them return `RenderedArtifact` (`C/outputs/a2ui/artifacts.py:54`): `artifact_id`, `mime_type`, `content: bytes|None`, `path`, `filename`, `title`, `surface`, `source_envelope_ref`, `deep_links`, `metadata`.

| Name | Class | Signature |
|---|---|---|
| `interactive-html` | `InteractiveHTMLRenderer(*, theme="light", layout="analytics")` (interactive_html.py:902) | `async render(envelope: CreateSurface, *, bake: bool=True) -> RenderedArtifact` (:920) |
| `ssr_html` | `SSRHTMLRenderer(*, theme="light", layout="analytics")` (ssr_html.py:180) | `async render(envelope, *, bake=True, deep_links: list[DeepLink]|None=None)` (:216). `PAGINATES=False` |
| `pdf` | `PDFRenderer(SSRHTMLRenderer)(*, theme="light")`, layout fixed to `print` (pdf.py:101) | `async render(envelope, *, bake=True, deep_links=None)` (:136). Uses weasyprint with charts drawn as static SVG (`_chart_svg`, :50). Needs the `ai-parrot-visualizations[a2ui-pdf]` extra. "No playwright path is shipped." |
| `echarts` | `EChartsRenderer()` (echarts.py:107) | `async render(envelope, *, bake=True, wrap_html: bool=False)` (:110). Returns the ECharts option JSON for the **first** Chart or Graph only, or an HTML wrapper when `wrap_html=True` |
| also | `adaptive_cards` (`AdaptiveCardsRenderer`, :212), `folium_map` | — |

- **Interactive HTML uses vendored Chart.js, not ECharts** (`_CHART_JS_PATH = formats/assets/chart.umd.min.js`, interactive_html.py:212). The ECharts bundle is used only by `echarts.py`. **This conflicts with the "ECharts only" decision.** A board renderer (or the Navigator-side renderer) must switch to ECharts, or the server-side HTML/PNG export will not match what users see live.
- **PNG / headless**:
  - **No A2UI renderer produces PNG.**
  - Playwright exists only in tools: `T/computer/backend.py:73` `AsyncComputerBackend` has `screenshot(full_page=False) -> bytes` (:248), `screenshot_element(selector)` (:485) and `navigate(url)` (:414). Scraping screenshots exist too. Playwright is an optional dependency (`ai-parrot-tools[scraping]`, `playwright>=1.52`).
  - weasyprint is used by `S/handlers/print_pdf.py:21` `PrintPDFHandler` and `T/pdfprint.py:90`.
  - A PNG export needs a new renderer (Playwright `set_content(html)` then `screenshot()`), or Navigator-side capture.

#### 9. AgentTalk / bot A2UI lift points (confirmed present)

- `C/bots/base.py:984` `_extract_last_linked_surface_result(self, tool_calls: list|None) -> dict|None` scans tool calls newest first. It takes the first successful dict result with `a2ui_envelope` plus an artifact of `type=="a2ui_linked_surface"`, and returns `_wrap_create_surface(...)` (from `C/outputs/a2ui/emission.py:49`).
- `C/bots/base.py:1008` `_extract_last_published_surface_id(self, tool_calls) -> str|None` returns the `surface_id` from the last successful `publish_surface` call.
- `ask()` lift at `C/bots/base.py:1617-1635`, with precedence interactive > infographic > linked. It sets `response.a2ui_envelope`, and `metadata["a2ui_surface_id"]` when a publish happened.
- `ask_stream()` lift at `C/bots/base.py:2177-2185` (the FEAT-611 "live S4" fix) sets `ai_message.a2ui_envelope` and `metadata.a2ui_surface_id`.
- The contract a ReportBuilderToolkit has to follow so its results reach the chat UI unchanged: tool results shaped `{"a2ui_envelope", "artifacts":[{"type":"a2ui_linked_surface"}]}`, or a tool named `publish_surface` that returns `{surface_id}`.

#### 10. Does NOT exist (searched under packages/*/src on f01a600f1, excluding tests)

| Item | Search | Result |
|---|---|---|
| `Report` / `ReportVersion` models (the only `Report` is the A2UI catalog component `ReportComponent`) | `class Report\b`, `ReportVersion` | absent |
| `/api/v1/reports` routes | literal | absent |
| Report store (`ReportStore`, `PgReportStore`, `report_store`) | regex | absent |
| `ReportBuilderToolkit` / `ReportBuilder` | regex | absent |
| `NavigatorWidget` A2UI component | literal | absent |
| Report or global parameters model (only per-source `ParamSpec`, plus FilterBar `parrot_param{source,name}`) | `ReportParam`, `report_param` | absent |
| Catalog HTTP route (only `/a2ui/capabilities`, which returns ids, not definitions) | `/a2ui/catalog`, `add_view(.*catalog` | absent |
| Per-source refresh endpoint (refresh re-runs ALL sources; per-source params are possible but not a per-source fetch) | `sources/{`, `/refresh/{source` | absent |
| Surface `PUT`, or a `PATCH` that changes the envelope (PATCH only changes visibility) | handler verbs | absent |
| Surface versions table (`ui_surface_versions`, `SurfaceVersion`) | regex | absent |
| `UISurfaceKind.report` (only dashboard, infographic, widget) | enum | absent |
| Page / Grid / Dashboard container component, or a 12-column layout | catalog names, `colSpan`, `gridColumn` | absent |
| `linkable` flag on `ComponentDefinition` | `linkable`, `bindable` | absent |
| HTTP route to list a surface's shares (`store.list_shares` exists) | routes | absent |
| Signed-URL primitive for surfaces (share tokens are opaque DB tokens; S3 presign exists for artifacts only) | — | absent |
| Report or board scheduled-job type (scheduler jobs are agent jobs plus callbacks) | — | absent |
| PNG renderer | — | absent |
| Persistent template or theme store (both registries are in memory) | — | absent |
| Startup wiring of `register_recipe_routes` in ai-parrot | callers | absent; only tests call it |

### Verified Codebase References — navigator-svelte + FieldSync



Snapshots (read-only): navigator-svelte `dev` @ 8c34c8d26 · fieldsync `/home/jelitox/repos/Trocdigital/fieldsync` branch `feat-581-tenant-aware-migrations` @ 9254d2ed · ai-parrot `dev` @ f01a600f1.
Paths are relative to each repo root.

---

#### 1. FieldSync: what it is and how `/api/v1/{tenant}/ui/surfaces` is wired

**What it is.** FieldSync is a separate aiohttp/navigator backend in the repo `Trocdigital/fieldsync` (deployed as the `fieldsync-api.*` host). In navigator-svelte its base URL is `config.fieldsyncBaseUrl = pick(env.PUBLIC_FIELDSYNC_BASE, apiBaseUrl)` (`src/lib/config.ts:62`, exported at :129). The env var is `PUBLIC_FIELDSYNC_BASE`, not `VITE_*`. When the var is blank, it falls back to the core API base (`config.ts:56-61`).

**It is not an HTTP pass-through proxy.** FieldSync imports ai-parrot as a Python library (wheel `ai-parrot-server[all]>=0.25.32`). It then mounts parrot's own handler classes, unchanged, under its tenant seam:
- `fieldsync/surfaces.py:24-27` imports `ProgrammeScopedView, declared_programme, programme_route_prefix` (seam), parrot's `RecipeHandler`, `PgUISurfaceStore, UISurfaceRecord` and `UISurfacesHandler`.
- `fieldsync/surfaces.py:241` defines `class ScopedUISurfacesHandler(ProgrammeScopedView, UISurfacesHandler)`. Through the MRO, the seam prologue runs first and parrot's `get/post/patch/delete` run after it.
  - `store` property override (:253-257) returns `ProgramScopedSurfaceStore(super().store, declared_programme(request))`.
  - `_refresh` override (:259-266) returns 403 when the body's `params.fieldsync_tenant` names a different tenant (`_rejects_foreign_tenant_stamp`, :46-76).
- `fieldsync/surfaces.py:182-238` defines `class ProgramScopedSurfaceStore`, a delegating wrapper built per request:
  - `save` stamps `recipe_params.fieldsync_tenant = program` (`PROGRAM_STAMP_KEY`, :43).
  - `update_envelope` puts back the stored stamp.
  - `list` and `list_shared_with` filter in Python on the stamp.
  - All other calls go through `__getattr__` (owner-or-token `get`, shares).
  - Parrot's table has no program column. Tenancy is carried only by the `recipe_params` stamp. Parrot's `UISurfaceRecord.tenant` field (`parrot/handlers/models/ui_surfaces.py:78`) exists but FieldSync does not use it for scoping.
- `fieldsync/surfaces.py:269-305` defines `ScopedRecipeHandler`. `put`/`delete` are superuser-only, and `post` (`/run`) has the same foreign-tenant guard.
- Routes are registered at `fieldsync/surfaces.py:553-565`:
  - `programme_route_prefix("/ui/surfaces")` plus `_SURFACE_SUFFIXES` (:311-317): `"" | /{surface_id} | /{surface_id}/refresh | /{surface_id}/share | /{surface_id}/share/{token}`
  - `/infographic_recipes` plus `"" | /{name} | /{name}/run`
  - Each route uses `app.router.add_view`, so every HTTP method (including parrot's PATCH visibility) is routed to the class.
- `programme_route_prefix(app_base)` returns `f"/api/v1/{{tenant}}{app_base}"` (`apps/tenancy/seam.py:102-115`). The repo has one rule: never hardcode `{tenant}`.
- `ProgrammeScopedView._iter` is at `apps/tenancy/seam.py:430-474`. It lets OPTIONS through, then runs `_run_prologue`: parse tenant → reserved-segment check → entitlement (superuser exempt) → provisioned-footprint check (`requires_provisioned=True`). After that, handlers read the tenant only through `declared_programme(request)` (:293).
- Composition root: `setup_surfaces(app, *, dsn=None, recipe_store=None, dataset_manager=None)` (`fieldsync/surfaces.py:618-667`) is gated on `USE_AGENT_SURFACES` (`settings/settings.py:396`, default False).
  - It installs `app["ui_surfaces_store"] = PgUISurfaceStore(dsn)` and `app["ui_surfaces_negotiation"]` (:321-332), the scope resolver (`FieldSyncSurfaceScopeResolver`, :115; a no-op on parrot wheels older than FEAT-535), the recipe wiring, the transformers and the routes.
  - It is called from `app.py:790` (import at :55).
- Parrot's native mount, for comparison: `packages/ai-parrot-server/src/parrot/manager/manager.py:2339-2343` mounts `/api/v1/ui/surfaces...`, with no tenant prefix.

**Recipe for `/api/v1/{tenant}/reports` (mirror FEAT-559):**
1. In parrot: build a `ReportsHandler(BaseView)` with a store property like `self.request.app["reports_store"]`, plus `PgReportStore`.
2. In FieldSync: add a new `fieldsync/reports.py` with `ScopedReportsHandler(ProgrammeScopedView, ReportsHandler)`, a `ProgramScopedReportStore` wrapper (or real use of the `tenant` column), `_register_routes` via `programme_route_prefix("/reports")`, and `setup_reports(app)` gated on a flag. Call it next to `setup_surfaces` in `app.py:790`.
3. Pin a parrot wheel version that includes the handler.

**Risks found:**
- **Route collision.** FieldSync already serves `/api/v1/reports/*` (FEAT-308 submission export and schedules, `apps/reporting/routes.py:20-66`: `POST|GET /api/v1/reports/schedules`, `DELETE /schedules/{schedule_id}`, `/{form_id}/export`).
  - `reserved_tenant_segments()` (`seam.py:118-156`) adds the literal `reports` to the reserved tenant names, so a tenant called `reports` is impossible. That is fine.
  - The bigger issue is naming confusion and the existing client. Navigator's widget client `src/lib/components/widgets/type/_fieldsync-reporting/reports-api.ts:10,33,48` calls `config.apiBaseUrl` + `/api/v1/reports/schedule` (singular, a different host). Choose a distinct segment (`/report_builder` or `/ui/reports`) or document the coexistence.
- **Parrot dev and FieldSync wrapper are out of sync.** Parrot dev's `PgUISurfaceStore.update_envelope(..., *, expected_updated_at=None)` (`models/ui_surfaces.py:656-662`) returns a bool. The linked-refresh path calls it with `expected_updated_at=` (`handlers/ui_surfaces.py:713-718`) and treats a falsy result as `409 stale refresh`. FieldSync's `ProgramScopedSurfaceStore.update_envelope(surface_id, envelope, recipe_params)` (:216-226) does not accept that kwarg and returns None. Once FieldSync installs a parrot wheel that has FEAT-598, linked-surface refreshes through FieldSync will raise a TypeError. Any new report store wrapper must forward `**kwargs` and return values.
- **Parrot version lag.** FieldSync already guards against older parrot wheels with try/except (`surfaces.py:29-32`, `_install_scope_resolver` :335-365). The reports lane will need the same version-gating discipline.

---

#### 2. Verified code context (navigator-svelte)

##### 2a. `src/lib/api/a2ui.ts` (298 lines)
- `const client = createApiClient(config.fieldsyncBaseUrl, { skipAuthRedirect: true })` :31. Every path goes through `tenantPath(program, path)`.
- `tenantPath(tenant, path): string` (`src/lib/api/tenantPath.ts:14`) throws `TypeError` when the tenant is empty and returns `/api/v1/${encodeURIComponent(tenant)}${path}`.
- Types:
  - `A2uiApiErrorKind` (:33-41) = `invalid_envelope|not_found|not_refreshable|share_gone|recipe_failed|lane_unavailable|tenant|unknown`
  - `class A2uiApiError(message, status, kind, detail?)` (:43-53)
  - `interface A2uiClient` (:55-75)
- The only export is `createA2uiClient(program: string): A2uiClient` (:135). Its methods:
  - `listSurfaces(kind?)` → GET `/ui/surfaces?kind=` → `data.surfaces` (:137-146)
  - `getSurface(id, share?)` → `{envelope, metadata}` (:148-157)
  - `getSurfaceHtml(id, share?)` → Blob, the only raw `fetch` (:159-189, fetch :166)
  - `saveSurface(req)` → POST, removes `recipe_params.fieldsync_tenant` (`stripProgramStamp` :113-120) (:191-205)
  - `patchSurface(id, patch)` (:207-217)
  - `refreshSurface(id, params, share?)` → POST `/{id}/refresh` with body `{params}` (:219-229)
  - `mintShare(id, {expires_at, ttl})` (:231-241), `revokeShare(id, token)` (:243-254), `deleteSurface(id)` (:256-262)
  - `listRecipes()` (:264-273), `getRecipe(name)` (:275-284), `runRecipe(name, params)` (:286-296)
- Errors: `statusToKind` (:78-96) maps 400/404/409/410/422/502/501. `toA2uiError` (:99-110) converts `FieldsyncTenantError` (`fieldsyncTenantError.ts:38`) to `'tenant'`.
- There is no SSE or streaming. **A reports client would copy this file's shape exactly**: a `createReportsClient(program)` over `/reports`.

##### 2b. Routes `src/routes/(app)/[programs]/reporting/`
- Files: `+layout.server.ts`, `+layout.svelte` (children only), `+page.svelte`, `surface/[surface_id]/+page.svelte`, and the tests `reporting-guard`, `reporting-shell`, `reporting-visibility-wiring` and `surface-route`. There are no `+page.ts` load functions; everything loads client-side.
- `+layout.server.ts` guard:
  - Bypass: `route.id === '/(app)/[programs]/reporting/surface/[surface_id]'` with `?share` (:21-23).
  - Otherwise: `isFieldsyncAdmin` (:29) or `isFieldsyncManager` (:32) passes. `isConfinedToRepMode` is redirected to `/${programs}/agent_rep_mode` (:35-36), and everyone else to `/${programs}` (:38). Helpers come from `$lib/helpers/rep-mode` (:11).
  - Login is enforced by the parent `[programs]` layout.
  - A `builder/[report_id]` route under `reporting/` inherits this guard automatically. A share bypass for reports would need its own `route.id` check.
- `+page.svelte`:
  - `client = $derived(createA2uiClient(program))` (:25-26), `loadSurfaces()` (:136-153), race-guarded `select(id)` (:123-134).
  - Actions: refresh (:160-165), delete with `ConfirmDialog` (:180-186), visibility via `patchSurface` (:199-216), share via mint/revoke (:507-514), HTML lane (:113-121).
  - Layout: `SurfacesSidebar` (:318-338), a collapsible aside (localStorage `reporting:list-collapsed` :68), a phone `AppSheet` (:487), and `<A2uiCanvas data={{create, metadata, program}} onRefresh onShare onOpenHtml onOpenTab/>` (:438-449).
- `surface/[surface_id]/+page.svelte`: `sessionId = uuidv4()` per tab (:18), reads `?share` (:22-23), `load()` → `getSurface` into a ViewState (:26-55) called from `$effect` (:68-74), `refresh()` (:57-66), per-kind error copy (:89-106), and `A2uiCanvas` (:109-113).

##### 2c. A2UI engine, registry and types (`src/lib/components/agents/canvas/a2ui/`)
- Folders: `basic/` (18 primitives), `parrot/` (Chart [ECharts], A2uiDataTable, A2uiDataGrid, Map, A2uiKpiCard, InfoCard, Timeline, Report, Infographic, FilterBar, HtmlDocument…), `cards/`, `schema/` (catalog.json, catalog_definition.json, common_types.json…), plus `filter-state.svelte.ts`, `a2ui-functions.ts`, `node-props.ts`, `json-pointer.ts` and the dialogs (`RefreshParamsDialog`, `ShareDialog`, `ConfirmDialog`).
- `a2ui-engine.svelte.ts`: `export class A2uiSurface` (:41), one per surface.
  - State:
    - `components = $state.raw(Map<string,A2uiComponent>)` (:48, replaced wholesale)
    - `dataModel = $state<Record<string,unknown>>({})` (:50)
    - `degraded = $state<DegradedRecord[]>([])` (:52)
    - `onAction?: (action, context) => void` (:59)
  - `constructor(create: CreateSurface)` (:64). A missing root degrades instead of throwing (:70-76).
  - API:
    - `resolve<T>(DynamicValue<T>, scope?)` (~:90, never throws)
    - `scopeFor(id)` (:104), `expandTemplate(tpl, scope?)` (:125)
    - `applyUpdateComponents(update)` (:205), `applyUpdateDataModel(update)` (:224; `/` replaces everything, `null` deletes)
    - `writeBack(path, value, scope?)` (:243), `degrade(id, component, reason)` (:257)
    - `dispatchAction(node, action, context={}, userActivated=false)` (~:270). Without `onAction`, only `openUrl` runs locally.
  - The editor and the agent can drive edits through `applyUpdateComponents` and `applyUpdateDataModel`.
- `registry.ts`:
  - `interface A2uiNodeProps { surface: A2uiSurface; node: A2uiComponent; scope?: TemplateScope }` (:44-48)
  - `a2uiRegistry = new Map<string, Component<A2uiNodeProps>>()` (:52)
  - `registerA2uiComponent(name, component)` (:54), `getA2uiComponent` (:58), `hasA2uiComponent` (:62)
  - `registerBasicCatalog()` (:69-90) and `registerParrotCatalog()` (:95-110) are idempotent and are called on every `A2uiCanvas` mount (`A2uiCanvas.svelte:45-46`).
  - Example: `registerA2uiComponent('KPICard', A2uiKpiCard as unknown as AnyA2uiComponent)` (:101).
- Dispatch: `A2uiNode.svelte:31` does `a2uiRegistry.get(node.component)`, then `<Comp {surface} {node} scope/>` (:47). An unknown component renders `Degraded` (:49-53).
- Leaf pattern: `parrot/InfoCard.svelte:7` has `let { surface, node, scope }: A2uiNodeProps = $props()` and `resolveProp<string>(surface,node,'title',scope)`. `resolveProp` is at `node-props.ts:13`.
- `A2uiCanvas.svelte`: `A2uiCanvasData { create: CreateSurface; metadata?: SurfaceMetadata; program: string }` (:20-24). The surface is `$derived(new A2uiSurface(...))` (:50-54), and it renders `<A2uiNode {surface} id={surface.rootId}/>` (:117).
- `src/lib/types/a2ui.ts`:
  - Bindings and values: `DataBinding{path}` :25, `FunctionCall{call,args?,catalogId?}` :29, `DynamicValue<T>` :36
  - Children and actions: `ChildTemplate{componentId,path}` :43, `ChildList` :47, `EventAction` :49, `A2uiAction` ({event}|{functionCall}) :56-58
  - `Extensions` (the `parrot_*` keys) :80-103
  - `A2uiComponent{id, component, catalogId?, child?, children?, weight?, accessibility?, checks?, action?, metadata?}` :112-122. Other props are free-form keys.
  - Messages: `CreateSurface{surfaceId,catalogId?,sendDataModel?,components,dataModel?,metadata?,rootId?}` :126, `UpdateComponents` :137, `UpdateDataModel` :143, `ActionMessage` :189
  - Surface API types: `SurfaceKind='dashboard'|'infographic'|'widget'` :216, `SurfaceMetadata` :218, `SurfaceResponse` :241, `SurfaceListResponse` :247, `PublishSurfaceRequest`, `PatchSurfaceRequest`, `ShareResponse` (~:258-286)
- **Adding `NavigatorWidget`:**
  1. Create `a2ui/parrot/NavigatorWidget.svelte`, or a new `a2ui/navigator/` folder. It takes `A2uiNodeProps` and reads `widget_id` and params with `resolveProp`.
  2. Register it inside `registerParrotCatalog()` (`registry.ts:95-110`), or in a new idempotent `registerNavigatorCatalog()`. A new function also needs calling in `A2uiCanvas.svelte:45-46` and `schema-conformance.test.ts:52`.
  3. Optional: add new `parrot_*` keys to `Extensions` (`types/a2ui.ts:80`).
  4. Optional: add an entry in `schema/catalog.json`. `KPICard`/`InfoCard` are not in it, so it is not required for rendering. `schema-conformance.test.ts:60-82` validates against these schemas.
  5. Add a colocated test.

##### 2d. Agent-chat canvas tabs
- `src/lib/components/agents/canvas/canvas-tab-manager.svelte.ts`:
  - `CanvasTabType` includes `'a2ui'` (:6-13). `CanvasTab{id,type,title,data,closable}` (:15-21). Module-level `tabs`/`activeTabId` (:25-26).
  - Exports `getTabs, getActiveTabId, getActiveTab, initCanvas, addTab(type, title, data=null): string (:57), removeTab, setActiveTab, updateTabData, updateTabTitle, resetCanvas` (:41-101).
- `canvas-registry.ts`:
  - `registry = new Map<CanvasTabType, Component<{data; previewMode?; agentId?}>>()` (:15)
  - `registry.set('a2ui', A2uiCanvas …)` (:32)
  - `registerCanvasComponent(type, component)` (:34), `getCanvasComponent` (:38), `hasCanvasComponent` (:42)
- **No caller opens an `'a2ui'` tab today.** `AgentChat.svelte` `addTab`s infographic, interactive, markdown, spreadsheet and chart (:724-1594) but never `a2ui`. The only mention is a comment at `A2uiCanvas.svelte:6`. `CanvasPanel.svelte:203` deliberately excludes `'a2ui'` from one list.
- The conversational and RPC lane (`maybeOpenA2uiCanvas`, `callAgentFunction`) is a Non-Goal of `sdd/specs/fieldsync-a2ui-surface-consumer.spec.md:42-48`. It is designed but not built, so the "agent" half of the builder must build this lane.
- A mirror copy lives under `src/lib/fn/components/agents/canvas/` (G0, untouchable).

##### 2e. Dashboard grid (`src/lib/components/dashboards/Dashboard.svelte`, 2028 lines, **legacy mode**: `export let`, `$:`, `createEventDispatcher`)
- Imports `Grid, { GridItem, type GridController } from 'svelte-grid-extended'` (L2). Settings: `cols = 12` (L88), `itemSize = { height: 10 }` (L89), `let gridController: GridController` (L92).
- `<Grid {itemSize} gap={5} {cols} collision={gridCollision} autoCompress={gridAutoCompress} bind:controller={gridController} on:change>` (L1545-1553).
  - `gridCollision` is `'push'` when `attributes.layout_free`, otherwise `'compress'` (L1361-1362).
  - `autoCompress=false` always. Setting it true caused an `effect_update_depth_exceeded` loop (L1363-1371).
- `<GridItem x y w h resizable={resizeEditable} movable={layoutEditable} bind:id={item.data.attributes.title} …>` (L1566-1582). There is a `moveHandle` slot (L1586-1603).
  - Items render via `{#each $storeDashboard.gridItems as item (item.data.widget_id)}` (L1556).
  - **The grid key is the widget TITLE.** There is no readOnly prop; read-only means movable and resizable are both false.
- Edit mode is a plain `let isEditMode = false` (L106). It feeds `$: layoutEditable = canMove && isEditMode` (L1346) and `$: resizeEditable = isOwner && isEditMode` (L1347). The toolbar sits under `{#if isEditMode}` (L1727).
- Contexts: `setContext('dashboard', storeDashboard)` (L310), `setContext('gridBridge', gridBridge)` (L315).
- `widget_location` shape: `{ [title]: {x,y,w,h,order}, timestamp }`.
  - Loaded by `loadV3Locations` or `loadV2Locations` (L501-508).
  - Saved via `updateWidgetLocation` (L544-563) with POST `/api/v2/dashboards/{id}` and `{attributes:{…, explorer:'v3', widget_location}}`.
- Helpers in `src/lib/helpers/dashboard/`:
  - `grid-controller.ts`: `readControllerItemsLocations(gridParams)` (L4), `syncGridItemsToParams(gridItems, gridParams)` (L14, matches on title), `getControllerItemsLocations` (L40, deprecated), `pushGridItemsToParams` (L50).
  - `grid.ts` re-exports those (L12-17) and adds:
    - Layout loading: `loadV2Locations(wl, dash, widgets, cols, isMobile)` (L22), `loadV3Locations(wl, widgets, cols, isMobile)` (L63), `loadGridLocations` (L120), `saveLocalStorageLocations` (L187)
    - Item operations: `cloneItem` (L298), `resizeCollapseItem` (L388), `removeItem(item, items, gridParams)` (L469)
    - `findFirstAvailableSlot`, `computeOrderByYX`, `applyLocationDeltas` (L600-601)
  - `publish-layout.ts`: `type PublishLayoutDeps = { gridController, dashboardId, storeDashboard, storeUser, postData, apiBaseUrl, dispatch, notifyError, isMobile, tick, setIsPublishing, getIsPublishing }` (L7-20). `publishLayout(deps): Promise<any|null>` (L22) runs only for the owner and not on mobile.
  - `dirty-diff.ts`: `interface GridItemLike` (L14), `isWidgetDirty(current, snapshot): boolean` (L39, compares x/y/w/h, title and fixed), `getDirtyWidgetIds(current, snapshot): Set<string>` (L54, keyed on widget_id).
- **Builder implication:** the builder's 12-column board should reuse `svelte-grid-extended` with the same `cols`, `itemSize` and `gap` and the pure helpers (`readControllerItemsLocations`, `findFirstAvailableSlot`, dirty-diff). It should key items by A2UI component `id`, not by title. Do not embed `Dashboard.svelte`: it is legacy, tied to the module and dashboard stores, and saves to `/api/v2/dashboards`.

##### 2f. JsonSchemaDrawer and settings
- `src/lib/components/forms/JsonSchemaDrawer.svelte` (legacy props, L20-33):
  - `open, mode:'new'|'edit', title, subtitle`
  - `schema: JsonFormField[], state, errors`
  - `submitting, primaryLabel, secondaryLabel, widthClass='max-w-2xl', allowPreview=true`
  - Events: `change {path,value,nextState}` (L115), `submit` (L146), `close` (L147).
- `JsonFormField` (`src/lib/json-schemas/types.ts:1`):
  - `key` (a dot-path), `label`
  - `type ∈ text|time|textarea|number|select|switch|icon|json|keyvalue|color|multiselect|multiselect-search|repeater|filter-builder|file-text|component`
  - `required, options, showIf(state), cols, section, order, fields, …`
- Sample: `src/lib/components/widgets/type/YouTube/setting.ts`.
  - `youtubeFormDefinition: JsonFormField[]` (L11-110). Its keys include `params.settings.general.fixed`, `params.settings.header.*`, `params_raw` and `attributes_raw`.
  - `export const drawerSettings: WidgetDrawerSettings` (L151) with `getState` and `transform(payload, widget)` (L155).
  - The type is defined at `src/lib/components/widgets/settings/types.ts:3-15`: `{subtitle?, schema, getState(widget), transform?, primaryLabel?, secondaryLabel?, liveTransformPaths?}`.
- **This can drive the A2UI inspector and the report parameter editor:** one `JsonFormField[]` per A2UI component type, plus `filter-builder` and `repeater` for parameters.

##### 2g. Standalone widget by widget_id (how NavigatorWidget would embed)
- Route `src/routes/(app)/share/widget/[id]/`:
  - `+layout.server.ts` uses the token from `?token=` or `locals.user.token`. It sends `authorization: Bearer`, or `x-api-key` when `locals.user.apikey` is set, and calls `getApiData(${apiBaseUrl}/api/v2/widgets/${id})`. It returns `{widget, user}`.
  - `+layout.svelte` is a bare `<main>`.
  - `+page.svelte`:
    - calls `storeUser.set(data.user)`;
    - copies the widget, sets `loaded=false` and `shared=true`, and turns off the toolbar `{collapse,close,clone,cut,copy}`;
    - renders `<WidgetBox widget={w}>{#snippet children({widget,fixed,isToolbarVisible,isOwner})}<Widget …/>{/snippet}</WidgetBox>`.
- Props:
  - `WidgetBox.svelte` (L30-45): `widget` and `children: Snippet<[WidgetBoxSlotProps]>` are required; `isEditMode, gridController, onResize, onRemove, onClone, …` are optional.
    - It wraps the widget in `writable(widget)` (L140).
    - It passes the slot `{widget: Writable, isToolbarVisible, fixed, isOwner, isDragging, isEditMode}` (L21-28, L330).
    - It reads the optional contexts `'dashboard'` (L127) and `'gridBridge'` (L131).
  - `Widget.svelte` (L14-40): `widget: Writable`, `isToolbarVisible`, `fixed` and `isOwner` are required; `reload`/`filter` are `$bindable`.
    - It reads `getContext('widgetActions')` (L42) and `getContext('dashboard')` (L43). Both are null-safe, e.g. `$dashboard?.filterTick` (L97).
  - `ComponentBase.svelte`: `{widget: Writable, children: Snippet<[{data}]>}`. It dynamically loads `base/{Api|Rest|Media}` based on the `widget_type_id` prefix. It is used through `Content.svelte`.
- **NavigatorWidget recipe:**
  1. Fetch the widget client-side with GET `/api/v2/widgets/{widget_id}` using `config.apiBaseUrl` and the session token. The report route has no server load that could do it.
  2. Set `loaded=false` and `shared=true` and disable the toolbar.
  3. Render it in `WidgetBox` + `Widget`.
  4. Optionally `setContext('dashboard', writable({...filterTick, filters}))` so global report parameters can drive widget filters.
- Risks:
  - `Widget` and `WidgetBox` are legacy and store-heavy (`storeUser`), and they do their own data fetching.
  - Global parameters reach a widget only through the `'dashboard'` filter context, not through A2UI bindings.
  - The widget's own data lives on the Navigator API host, not on FieldSync or parrot.

##### 2h. Widgets side panel (FEAT-567) + cloneWidget
- `src/lib/components/widget-library/WidgetLibraryPanel.svelte` takes runes props `{programId, open, oninsert:(t: WidgetTemplate)=>void}` (L9-17).
  - Templates come from `loadWidgetTemplates(programId)`, which calls GET `/api/v2/widgets-template?program_id=` (`widgets-template-fetch.ts:47-49`).
- It is mounted in `src/routes/(app)/[programs]/+layout.svelte:326-340` inside `<SidePanel open={$widgetPanelOpen}>` with `oninsert={handleWidgetPick}` (L71 → `requestWidgetInsert`).
  - **It auto-closes on any route that is not a dashboard (L66-69).** The builder route would need to be allow-listed, or would need its own panel instance.
- Store bridge `src/lib/stores/widgetPanel.ts` (legacy writable):
  - `widgetPanelOpen` (L6), `widgetInsertRequest: Writable<WidgetTemplate|null>` (L9)
  - `openWidgetPanel()` (L12), `closeWidgetPanel()` (L19), `toggleWidgetPanel`, `requestWidgetInsert`
  - The consumer is `modules/Module.svelte:584-588`, which forwards to `dashboard.newWidget`. `Dashboard.svelte:375-377,956` then runs `createNewWidget`: PUT `/api/v2/widgets`, then POST the dashboard's widget_location (`helpers/dashboard/widget.ts:26-56`).
- `cloneWidget(sourceWidgetId: string, destDashboardId?: string, opts: CloneWidgetOptions = {}): Promise<CloneWidgetResult>` (`helpers/dashboard/widget.ts:269`):
  - Types: `CloneWidgetOptions{titleSuffix?, allowCrossProgram?}` (L199), `CloneWidgetResult{widget, location, dest_dashboard}` (L204), `CloneWidgetError` with codes `CLONE_BLOCKED_PARENT|SHARED|CROSS_PROGRAM` (L210).
  - Flow:
    1. GET the widget.
    2. Block when it has a parent, or when it is shared and the user is not a superuser.
    3. GET the destination dashboard and run the cross-program check.
    4. PUT `/api/v2/widgets` (via `buildClonePayload` L236, 3 retries on duplicate titles).
    5. Place it with `resolveFreePositionFromLocation` (6×10).
    6. PATCH the destination dashboard's widget_location. On failure, DELETE the new widget to roll back (L335-355).
  - Used at `Dashboard.svelte:706`.
  - **It requires a destination dashboard.** For reports, the pick should insert a `NavigatorWidget{widget_id}` node, either by reference or by cloning into a hidden "report widgets" dashboard. That is a decision to make.

##### 2i. Module notifications scheduling (FEAT-511), the candidate for scheduled delivery
- `src/lib/api/module-notifications.ts`: `createApiClient(config.apiBaseUrl, {skipAuthRedirect:true})` (L17), base `/api/v1/modules/${moduleId}/notifications` (L19). A mock is gated by `VITE_NOTIFICATIONS_MOCK === '1'` (L22-25).
  - `listSchedules(moduleId)` (L74)
  - `createSchedule(moduleId: number, input: NewSchedule)` (L83-95, POST)
  - `updateSchedule(moduleId, id, Partial<NewSchedule>)` (L97, PATCH)
  - `pauseSchedule` / `resumeSchedule` (L117/L125)
  - `deleteSchedule` (L133)
  - `getContentTree(moduleId)` (L145)
  - `sendNow(moduleId, id): Promise<SendNowReport{status, links, deliveries, errors}>` (L154-175)
  - `listTemplates()` (L177)
- Types in `src/lib/types/module-notifications.ts:32-49`:
  - `ModuleNotificationSchedule{ id, name?, description?, enabled, channels:('teams'|'email')[], recipients:{name, provider, address}[], schedule_type:'daily'|'weekly', schedule_config:{time:'HH:MM', days?, tz}, template, scope:{exclude_modules, exclude_dashboards}, next_run, last_run, run_count }`
  - `NewSchedule` (L49)
- UI: `src/lib/components/dashboards/NotificationsPanel.svelte` takes props `{module, onclose}` (L33-38). Submit (L215-240) uses `<JsonSchemaDrawer allowPreview={false}>` (L627-643). Its schema is `buildNotificationFields()` in `dashboards/notifications-setting.ts:26`.
- **Fit for reports:**
  - The schedule is keyed by **moduleId**, on the Navigator API host. It is not keyed by report and is not on FieldSync or parrot, and its scope is modules and dashboards.
  - Report scheduling needs a new `scope.report_id` (or a parrot-side scheduler) plus a report export/render endpoint.
  - The payload shape (channels, recipients, schedule_type, schedule_config, tz) and the `NotificationsPanel` + `buildNotificationFields` UI can be reused as a template.
  - Do not confuse it with FEAT-308 (FieldSync `/api/v1/reports/schedules`, which covers form-submission exports only).

---

#### 3. Does NOT exist (verified by grep on navigator-svelte @ 8c34c8d26)
| Item | Evidence / nearest thing |
|---|---|
| `reporting/builder/[report_id]` route | `reporting/` contains only `+layout*`, `+page.svelte` and `surface/[surface_id]`. |
| Reports API client (`/api/v1/{tenant}/reports`) | Nothing. The only "reports" clients are `_fieldsync-reporting/reports-api.ts` (FEAT-356 → FEAT-308 `/api/v1/reports/schedule` export, on `apiBaseUrl`) and `ScheduledReports` widget, both unrelated. `admin/reports/[report]` is a legacy admin model page. |
| `NavigatorWidget` A2UI component | No match for `NavigatorWidget` in `src/`. The registry has only the basic and parrot catalogs. |
| Linked lane (`parrot_data_sources`) on the frontend | 0 matches in `src/`. It **does exist in parrot dev** (FEAT-598, spec `a2ui-linked-surfaces.spec.md` status approved): `parrot/outputs/a2ui/linked/{service,executor,schema,models}.py` and `UISurfacesHandler._refresh_linked` (`handlers/ui_surfaces.py:649,688-736`). |
| A2UI editor / inspector | No editor, inspector or selection state. The engine is render-only (`A2uiSurface` has no edit API besides `applyUpdate*`). |
| Report parameters UI (typed global params) | None. The nearest is `a2ui/RefreshParamsDialog.svelte` (FEAT-560 M8), which has props `{open $bindable, params?: Record<string,unknown>, onSubmit(params)}`, untyped name/value rows, and hides `fieldsync_tenant`. There is also `FilterBar` plus `filter-state.svelte.ts` in parrot components. |
| `share/report` route | None. Existing share routes: `share/{program,form,module,dashboard,widget}`. Surface sharing works through `reporting/surface/[id]?share=token` and the guard bypass (`+layout.server.ts:21-23`). |
| Agent → `'a2ui'` canvas tab | It is registered (`canvas-registry.ts:32`), but no caller opens it, and the chat/RPC lane is a Non-Goal of FEAT-559/560. |

---

#### 4. Constraints (CLAUDE.md + prior specs)
- **`src/lib/fn/**` is untouchable (G0).** `src/lib/fn/README.md:42-51`: mirrored FN code is never edited or reformatted; re-sync with `scripts/fn-sync.mjs`. Prior specs list it as an explicit non-goal (`sdd/specs/module-notifications-panel.spec.md:59,247`). A mirror of `agents/canvas` exists under `src/lib/fn/components/agents/canvas/`, so edit only the `src/lib/components/...` copy.
- **Desktop-only editing vs mobile-first:**
  - CLAUDE.md:83 requires a mobile-first layout, since about 99% of FieldSync users are on phones, with QA at 320/375/414.
  - Grid editing is already desktop-only by convention: `publishLayout` returns early on mobile (`publish-layout.ts:22`), and `dashboard-edit-discovery.spec.md:65` checks `!isMobileDevice()`.
  - The builder should therefore be desktop-only for editing, with a read-only responsive viewer, and the spec must state the phone fallback explicitly.
- **Tests:** import from `@testing-library/svelte/svelte5` (CLAUDE.md:76,99). Use Vitest + jsdom, colocated `*.test.ts`, and `*.integration.test.ts` for integration tests.
- **Legacy stores vs runes** (CLAUDE.md:65-75): do not mix `$:` with rune stores.
  - Legacy: `Dashboard.svelte`, `JsonSchemaDrawer` and `widgetPanel.ts`.
  - Runes: the `A2uiSurface` engine, `WidgetLibraryPanel` and the reporting pages.
  - The builder should be runes-first, with thin adapters at the legacy boundaries (`WidgetBox`/`Widget` writables, `widgetInsertRequest`, the drawer's `on:` events).
- **SSR:** guard `window`, `document` and `localStorage` with `browser` from `$app/environment` (CLAUDE.md:79-80, adapter-node SSR on). The reporting pages already load client-side only (no `+page.ts`), so follow that pattern.
- **API hosts:** FieldSync calls use `config.fieldsyncBaseUrl` (`PUBLIC_FIELDSYNC_BASE`) with `createApiClient(..., {skipAuthRedirect:true})` and `tenantPath()`. Navigator widget, dashboard and notification calls use `config.apiBaseUrl`. Never send `fieldsync_tenant`; the server stamps it.
- **Workflow:** branch off `dev`. Never auto-commit; stage specific files only (CLAUDE.md:89-91). No absolute `/home/...` paths in code (CLAUDE.md:95). DB-structure changes (`navigator.*`) need SQL migrations (CLAUDE.md:103).
- **Widget conventions:** `classbase` is case-sensitive and matches the folder name, and `widgets.title` equals the `widget_location` key (CLAUDE.md:56-58). New settings UIs use `setting.ts` + `JsonSchemaDrawer` (CLAUDE.md:60).
- **ECharts only:** A2UI `parrot/Chart` already renders with ECharts (`fieldsync-a2ui-surface-consumer.spec.md:45`). `chart-contract.ts` / `AppChartConfig` are marked read-only in that spec.
