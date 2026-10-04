# N4 — navigator-api backend inventory (dashboards / widgets / templates / modules / programs)

- Repo: `/home/jelitox/repos/trocglobal/navigator-api` (read-only, not pulled)
- HEAD: `a3b38a1d45defe3ced480812e0d64901a9b3667d` (2026-01-14, "Merge pull request #954 …") — likely behind origin.
- Libs (uv.lock): `navigator-api` 2.14.5 (provides `ModelView`), `querysource` 3.17.4.
- ai-parrot cross-check at `dc3e3a548` (2026-09-30).
- Paths below are relative to `navigator-api/` unless prefixed `ai-parrot:`.
- **No DDL in repo.** Tables, views and triggers (`vw_active_widgets`, `update_slugify()`) live only in the DB. Columns below come from the asyncdb models, which use `strict=True`, so they match the DB columns the API can see.

---

## 1. Models (`NAVIGATOR_SCHEMA` = `navigator`, settings/settings.py:77)

### navigator.dashboards — `Dashboard` resources/dashboards/models.py:9-57
| col | type | notes |
|---|---|---|
| dashboard_id | UUID PK, db_default auto | :11 |
| name | str, required | :14 |
| description | str | |
| params | jsonb | UI flags, e.g. `{closable, sortable, showSettingsBtn}` |
| enabled / shared / published / allow_filtering / allow_widgets | bool, default False | :17-21 |
| attributes | jsonb | `{cols, icon, color, explorer:"v3", widget_location:{…}, sticky, disable_drag, operational_date…}` (KB) |
| dashboard_type | str | the agent defaults it to `"3"` |
| slug | str | `__post_init__` sets `slugify(name,"_") + "_" + random` (:47-51) |
| position | int, default 1 | sort order within a module |
| cond_definition | jsonb | |
| widget_location | jsonb (**legacy column**) | :31; WidgetLocation endpoint reads/writes this column |
| module_id | int | FK to navigator.modules (not declared in the model) |
| program_id | int | FK to auth.programs |
| user_id | int | owner (draft/personal); NULL = system |
| render_partials, save_filtering | bool | |
| conditions | jsonb | filtering definition (`filtering`, `filteringadv`, `share`) |
| filtering_show | jsonb | |
| is_system | bool, default False | :41 (publish flag used by ai-parrot) |
| created_by | int | |

### navigator.widgets — `Widget` resources/widgets/models.py:67-127
Columns: widget_id UUID PK, widget_name, title, description, url, params jsonb, embed, attributes jsonb, conditions jsonb, cond_definition jsonb, where_definition jsonb, format_definition jsonb, **query_slug jsonb**, save_filtering, master_filtering (def True), module_id, **program_id (req)**, **dashboard_id UUID (req)**, template_id UUID, widget_slug (auto `slug(widget_name|title)_rand`, :113-121), widgetcat_id, allow_filtering, filtering_show jsonb, widget_type_id (FK widget_types.widget_type), user_id, active (def True), published (def True), inserted_at/by, updated_at/by.
- Relations: widget → dashboard (N:1), widget → template (N:1, optional), widget → widget_type, widget → widgets_categories (widgetcat_id; no model in the API).

### navigator.vw_active_widgets — `WidgetVw` (read model) models.py:18-64
The widget columns plus `widget_type`, `classbase`, `program_slug`, `published`. Per the KB, the view resolves inheritance with `COALESCE(widget.field, template.field)` (ai-parrot:agents/navigator/kb/navigator_operations.md:688-696). GET /widgets uses this view, so it returns the effective config after inheritance.

### navigator.widgets_templates — `WidgetTemplate` models.py:130-171
template_id UUID PK, widget_name, title, description, url, active, params/attributes/conditions/cond_definition/where_definition/format_definition/query_slug jsonb, master_filtering (def False), widget_slug, program_id (NULL = global template), **widget_type_id (req)**, **widgetcat_id (req)**, allow_filtering, filtering_show, inserted/updated_at/by. Not `strict`. About 1,218 rows (KB).

### navigator.widget_types — `WidgetType` models.py:200-209
widget_type PK (e.g. `api-echarts`), description, classbase, enabled. About 108 rows. ai-parrot also reads a `category` column (toolkit.py:2245) that the API model does not have.

### Others
- `navigator.user_pins` (id, widget_id, user_id, created_at) :174; `navigator.user_likes` (id, object_type, object_uuid, user_id) :186; `navigator.widgets_groups` (group_id, widget_id) :212. No handler is routed for widgets_groups.
- `navigator.modules` — `Module` resources/modules/models.py:11-50: module_id, module_name, module_slug (auto), classname, active, description, attributes jsonb (menu: icon, order, …), parent_module_id (menu tree), program_id, allow_filtering, filtering_show, conditions, inserted_at/updated_at.
- `navigator.vw_group_modules` (ModulevW :53), `navigator.client_modules` (client_id, program_id, module_id PK; :84), `navigator.modules_groups` (group_id, module_id, program_id, client_id PK; :108). Visibility is client × group × module.
- `auth.programs` — `Program` resources/programs/models.py:22-61 (program_id, program_name, program_slug immutable, attributes, conditions, filtering_show, allow_filtering, abbrv, image_url…). Also `auth.program_categories`, `auth.program_clients`, `auth.program_attributes`, `auth.program_groups`.
- `troc.user_filters` — `UserFilters` resources/savefiltering/models.py:5-24 (filter_id, filter_name, program_slug, conditions jsonb, user_id). Stores saved filter presets.
- **PowerBI "report/page" concept:** `navigator.pbi_reports` (report_id, program_id, program_slug, abbrv, report_name, description), `navigator.pbi_pages` (page_name PK, report_id, sort_order…), `navigator.pbi_pages_permissions` (page_name, user_id…). resources/pbi/models.py:8-83.

### widget_location format (KB navigator_operations.md:298-325 + toolkit)
- Modern format, in `dashboards.attributes.widget_location`: `{"timestamp": <ms>, "<Widget Title>": {"h":37,"w":12,"x":0,"y":0}, …}`. Keys are the widget **title** (falling back to widget_name, then id). The grid is 12 columns. The timestamp should be bumped whenever the layout changes.
- Legacy format, in the `dashboards.widget_location` column: `{"lobipanel-parent-stateful_2977_0": {"<widget-uuid>": 0}}`.
- **Mismatch:** the API's `/dashboard/widgets/location` endpoint (resources/widgets/location.py:26-41) only reads and patches the legacy column. ai-parrot writes `attributes.widget_location` (toolkit.py:1945-1962, 2046-2056).

## 2. Endpoints (app.py; all under `if SERVICES:` app.py:264)
All handlers subclass `navigator.views.ModelView`. `configure(app, path)` registers `{path}`, `{path}/{id}` and `{path}{meta}`; `:meta` returns the model columns. Verb semantics (venv navigator/views/model.py):
- GET :449 — get or filter
- PATCH :691 — partial update
- PUT :907 — insert
- POST :1062 — update-or-create
- DELETE :1400

`@service_auth` loads the session but **has no permission checks** (TODO at :111).

| METHOD PATH | handler | purpose / notes |
|---|---|---|
| GET/PUT/POST/PATCH/DELETE `/api/v2/dashboards[/{id}]` (+ `/api/v2/dashboards/{duid}`) | DashboardManager dashboards/handlers.py:16 (app.py:308-311) | **GET list** (:104-141): query params `program_id`, `module_id`, `explorer`, `enabled`. Unless `explorer=false` it filters `user_id=me, module_id=NULL` (personal explorer boards); with `explorer=false` it filters `user_id IN (NULL, me)` (system boards plus mine), optionally by module. Results are sorted by `position`. **GET one** (:72-103): non-superusers are restricted to `program_id IN session.programs`, or to ownership when they have no programs. There is a "TODO: cover shared dashboards" (:95). Writes: `user_id` is auto-set for non-superusers (:48-54) and `created_by` is set. Non-superuser writes without an id are scoped to `{user_id}` (:31-37). |
| POST `/api/v2/dashboard/clone[/{id}]` (`?duid=` or body `dashboard_id`) | DashboardClone :143-295 (app.py:312) | Copies the dashboard as `"<firstword>-<hex>"`, owned by the caller, **keeping the same slug** (:184). Clones every widget from `vw_active_widgets` (template-merged values) with the caller's user_id. Body `module_id` can retarget the module. Does not copy `is_system` (defaults False). |
| GET/PATCH `/api/v2/dashboard/widgets/location[/{dashboard_id}]` | WidgetLocation widgets/location.py:6 (app.py:319-326) | Returns or patches **only** `{widget_location}` (legacy column). PUT/DELETE raise NotImplemented. This is the layout-save endpoint. |
| GET `/api/v2/widgets[/{uid}]` | WidgetManager widgets/handlers.py:22 (app.py:315-316) | Reads from `vw_active_widgets`, filterable by any column (e.g. `?dashboard_id=`). Each row is enriched with `like` and `pin` for the current user (:76-99). |
| PUT `/api/v2/widgets?uid=<template_id>` | WidgetManager.put :107-175 | **Creates a widget from a template.** Body is `{dashboard_id, program_id?}`. Copies only program_id, widgetcat_id and widget_type_id; the rest is inherited through the view's COALESCE. Returns 202 `{message, data}`. Without `uid` it does a plain ModelView insert. |
| POST `/api/v2/widgets/{id}` | WidgetManager.post :180-224 | `Widget.updating`. Non-superusers can only update their own widgets (`user_id` filter). |
| PATCH/DELETE `/api/v2/widgets/{id}` | ModelView default | no ownership check |
| CRUD `/api/v2/widgets-template[/{id}]` | WidgetTemplateManager widgets/template.py:7 (app.py:329-331) | GET with query params returns `active AND program_id=X` plus global (`program_id NULL`) templates (:58-72). `widget_slug` is auto-generated as `name-<hex>`, and `updated_by` is set automatically. |
| CRUD `/api/v2/widget-types[/{widget_type}]` | WidgetTypeManager handlers.py:17 (app.py:334-337) | plain CRUD |
| CRUD `/api/v1/interactions/likes`, `/api/v1/interactions/pin` | UserLikeHandler / UserPinHandler handlers.py:226-244 | user_id is auto-set |
| CRUD `/api/v2/save-filtering` | saveFilteringManager savefiltering/handlers.py:5 (app.py:340) | per-user saved filters (troc.user_filters) |
| CRUD `/api/v1/modules`, `/api/v1/module_clients`, `/api/v1/module_groups` | ModuleManager etc. modules/handlers.py:10-24 (app.py:292-300) | plain CRUD; GET reads `vw_group_modules` |
| GET `/api/v2/modules[/{program_slug}]` | ModulesServices resources/module.py:15-148 (app.py:303-305) | Menu for the user: raw SQL on `vw_group_modules`, filtered by request client (Origin subdomain) and session groups. |
| POST `/api/v2/modules` | module.py:150-307 | **Superuser only.** Creates the module plus client_modules and modules_groups rows, and/or sets `dashboards.module_id` when `dashboard_id` is given (:250-283). |
| PUT `/api/v2/modules` | module.py:309+ | Superuser only. Updates the module and replaces its group and client assignments. |
| CRUD `/api/v1/programs`, `/api/v1/program_{groups,clients,attributes,categories}` | programs/handlers.py:68-106 (app.py:281-289) | ProgramManager filters `program_slug` to the session's programs (:72-80). |
| GET `/api/v1/programs_user[?client_slug=]` | ProgramUserHandler :20-66 | programs in the session, intersected with the client's programs |
| CRUD `/api/v1/pbi_reports`, `/api/v1/pbi_pages`, `/api/v1/pbi_permissions` | resources/pbi/views.py (app.py:214-216) | PowerBI report and page registry plus per-user page permissions. SQL is built with f-strings (injection-prone, :19-21 etc.). |
| GET/POST `/api/v2/services/queries/{slug}[:fmt]`, `/api/v3/queries/{slug}{meta}`, `/api/v1/management/queries/{slug}` | QuerySource (app.py:355-357; venv querysource/services.py:93-160) | **Widget data plane.** `:fmt` / `queryformat` choose the output writer: json, csv, tsv, excel, pdf, html, report, xml… (querysource/outputs/writers/*). This is the only "export" mechanism. |

There are **no** dedicated endpoints for share, export, publish, versioning or layout-save, other than the WidgetLocation PATCH above.

## 3. How a widget gets data; how templates define defaults
- Frontend chain: `widget_type_id` → `widget_types.classbase` → Svelte `src/lib/components/widgets/type/${classbase}/${classbase}.svelte` (ai-parrot:agents/navigator/kb/widget_catalog_media.md:12-16).
- The `widget_type` prefix selects the base loader:
  - `api-*`: fetch QuerySource `query_slug.slug`
  - `media-*`: static data from `format_definition` / `params`
  - `rest-*`: call the raw `url`
- `query_slug` shapes (KB :643-674): `{"slug":"x"}`; with `options`, `hlevel`, `comparison`, `comparison_period`, `v3`, `conditional_filtering`; `{"dashboard":"photoFeed"}` (internal reference); or multi `{"slug":[{"Label":"slug"}]}`.
- `conditions` hold filter defaults and selectors, using date tokens such as CURRENT_DATE, FDOM, LDOM… (KB :589-606). `where_definition` and `cond_definition` hold extra where clauses. The dashboard-level `conditions.filtering` drives the master filter bar (`master_filtering` on widgets).
- `format_definition` is type-specific: api-table column-index formatters, api-pqtable column defs, `{html}` for the wysiwyg widget, `{url,…}` for iframes (KB :609-640). `params` holds the type config, e.g. `params.graph.type` for echarts and `params.card.cards` for cards.
- Templates: about 99.9% of widgets carry a `template_id`. The widget overrides only the fields that differ, and `vw_active_widgets` merges them with COALESCE. `PUT /widgets?uid=` creates a near-empty widget that inherits everything. A `program_id NULL` template is global.

## 4. Draft/publish, versioning, sharing
- No lifecycle endpoint in navigator-api. The state lives in flags only:
  - dashboard: `published`, `enabled`, `shared`, `is_system`, `user_id`
  - widget: `published`, `active`
- The ai-parrot convention (FEAT-119, `nav_publish_dashboard`, ai-parrot:packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py:1582-1690): a draft is `is_system=False, user_id=<owner>`; publishing flips it to `is_system=True, user_id=NULL` in one UPDATE. Only the owner or a superuser may publish, and the call is idempotent.
- The API's GET list effectively treats `user_id NULL` as "system" (handlers.py:119).
- `shared` is a bool with no implementation. The "TODO: cover shared dashboards" is at handlers.py:95. There are **no share tokens and no versioning** (only inserted/updated_at on widgets and templates). Soft delete is the convention (`active` / `enabled = false`, KB :834).
- `conditions.share` in dashboards is a callback-action config (an API slug, method and callback), not sharing.
- ai-parrot has its own sharing in `navigator.ui_surfaces` + `navigator.ui_surface_shares` (opaque revocable tokens, `read+refresh`, expiry, `claimed_by`; visibility private|tenant|groups) — ai-parrot:packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py:63-154. Routes: `/api/v1/ui/surfaces[/{id}[/refresh|/share[/{token}]]]` (ai-parrot:.../parrot/manager/manager.py:2339-2343).

## 5. Existing report / template / page concepts
- **widgets_templates**: reusable widget configs. This is the closest thing to "report components".
- **pbi_reports / pbi_pages / pbi_pages_permissions**: PowerBI report → page registry with per-user page ACL. It is metadata only, with no layout.
- **Dashboards are the "pages"**, grouped in modules (the menu tree via `parent_module_id`) within a program.
- **QuerySource writers** `report.py`, `pdf.py`, `excel.py`: server-side rendering of a single query's output (pygal/seaborn/matplotlib charts). No multi-widget report.
- **user_filters**: saved filter presets (`troc` schema).

## 6. ai-parrot tools that touch these tables
`NavigatorToolkit(PostgresToolkit)` at ai-parrot:packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py:42 uses `tool_prefix="nav"`, giving tool names like `nav_create_dashboard`. **It calls no HTTP endpoints.** It writes SQL directly through asyncdb to the tables whitelisted at :77-83: navigator.modules, client_modules, modules_groups, dashboards, widgets, widgets_templates, widget_types (plus reads of auth.*). It runs its own ACL checks (`_check_program/module/dashboard/write_access`, :429-613), and every write is two-phase: `confirm_execution` first returns a plan for approval.

| tool | line | tables / effect |
|---|---|---|
| nav_create_program / update / get / list | 638 / 821 / 873 / 903 | auth.programs + client_modules/modules_groups |
| nav_create_module / update / get / list | 946 / 1162 / 1218 / 1246 | navigator.modules (+ setval sequence fix :1087), client_modules, modules_groups |
| nav_create_dashboard | 1334 | INSERT dashboards. Idempotent on (name, module, program). Defaults: `is_system=False`, `published=True`, `dashboard_type "3"`, `attributes.explorer "v3"`, `widget_location {}` |
| nav_update_dashboard / get / list | 1448 / 1502 / 1523 | dashboards |
| nav_publish_dashboard | 1582 | is_system→True, user_id→NULL |
| nav_clone_dashboard | 1693 | copies the dashboard as a draft (`published=False`, `is_system=False`, owner = caller) plus its raw widget rows |
| nav_create_widget | 1847 | INSERT widgets (default `api-echarts`, widgetcat 3). `grid_position {h,w,x,y}` is merged into `dashboards.attributes.widget_location[title]` (:1940-1962) |
| nav_update_widget | 1980 | UPDATE widgets; updates the grid via jsonb_set (:2046-2056) |
| nav_get_widget / list_widgets | 2062 / 2091 | widgets |
| nav_assign_module_to_client / group | 2152 / 2189 | client_modules / modules_groups |
| nav_list_widget_types / categories | 2230 / 2241 | widget_types |
| nav_get_widget_schema | 2290 | widget_types, plus the newest template and a widget example (the JSON shapes) |
| nav_find_widget_templates | 2358 | widgets_templates |
| nav_search_widget_docs / get_full_program_structure / search | 2392 / 2427 / 2487 | KB plus modules, dashboards and widgets |

KB used by the agent: ai-parrot:agents/navigator/kb/{navigator_operations,widget_catalog_top16,widget_catalog_media,widget_types_compact}.md. Tests: ai-parrot-tools/tests/unit/test_navigator_*.py.

---

## Report builder relevance

**Reusable pieces**
- Board/page = `navigator.dashboards`: it already has an owner, program/module scoping, position ordering, a JSONB `attributes` for layout, `conditions` for page-level filters, and draft/publish flags (`is_system` + `user_id`, `published`, `enabled`).
- Block = `navigator.widgets` with `query_slug` (QuerySource data binding), `params` / `format_definition` (render config) and `conditions` / `where_definition` (filters).
- Component library = `widgets_templates` plus `widget_types` (classbase → Svelte component). Template inheritance through `vw_active_widgets` gives "template + override" for free.
- Clone (`/api/v2/dashboard/clone`, `nav_clone_dashboard`) works as "duplicate report". `save-filtering` works for saved report parameters. QuerySource `:xlsx|pdf|csv` works for per-block export.
- ai-parrot `ui_surfaces` / `ui_surface_shares` already give tokenized sharing, tenant/group visibility and refresh (recipe replay). It is the natural home for AI-generated report snapshots.

**Hard constraints**
- `widget_types.classbase` must equal a Svelte directory and file name (`type/${classbase}/${classbase}.svelte`). A new block type needs a DB row **and** a frontend component.
- Layout keys are **widget titles**, not ids (`attributes.widget_location["<title>"]={h,w,x,y}`, 12 columns, plus `timestamp`). Duplicate or renamed titles break placement, so a rename must also rewrite the layout key.
- Two layout stores: the API PATCH endpoint touches only the legacy `widget_location` column, while the modern UI and ai-parrot use `attributes.widget_location`. Verify which one navigator-svelte saves through.
- Widgets require `program_id` and `dashboard_id`. Templates require `widget_type_id` and `widgetcat_id`.
- Slugs are generated by DB triggers and `__post_init__`, and clone reuses the source slug, so slug is not unique.
- `program_slug` is immutable. Soft delete only.
- Module visibility needs client_modules plus modules_groups rows for every client and environment.
- `strict=True` models reject unknown columns, so there is no room for new fields (report metadata, version, sections) without DB migrations.

**Gaps**
- No report/document entity: no ordered sections, text blocks, page breaks or print layout. Dashboards are grids only.
- No versioning or history, and no draft copy of a published board (publishing mutates in place).
- No share tokens. `shared` is unused and the endpoints have no shared-dashboard read path.
- No multi-widget export (PDF/XLSX of a whole board), no scheduling, no snapshot of the data.
- Permissions are weak: `service_auth` does no permission check, PATCH/DELETE on widgets have no ownership check, and pbi views build SQL with f-strings.
- Templates have no versioning. Template edits silently change every inheriting widget through COALESCE.
- The DB schema is undocumented in this repo (no DDL for the views or triggers).

**Suggested split:** keep live interactive boards in `navigator.dashboards` / `widgets` (reuse templates and QuerySource). Persist report-builder documents (pages, sections, versions, share tokens, snapshots) in ai-parrot, next to `ui_surfaces`, referencing navigator `widget_id` / `template_id` / `query_slug` rather than extending the strict navigator models.
