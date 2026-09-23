---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-tools, ai-parrot-server, admin-ui, docs]
tags: [a2ui, querysource, linked-surfaces, ui-surfaces, transform-dsl, widgets]
---

# Brainstorm: A2UI Linked Surfaces (data-source descriptors instead of baked data)

**Date**: 2026-09-15
**Author**: Jesus Lara (discovery with Claude, same session as the QuerySource `describe-queryslug` brainstorm)
**Status**: exploration
**Recommended Option**: A
**Revised**: 2026-09-24 — re-verified against FEAT-558 `QuerysourceToolkit`
(landed 2026-09-17, replaces the never-created "FEAT-567") and QuerySource
5.0.0 (in production: FEAT-148 `describe`, `/api/v3/queries/{slug}`, tenant
slug URLs). Two extra discovery rounds; decisions under "Resolved on
2026-09-24". **Second pass, same day:** cross-checked against FEAT-147
per-tenant queries and FEAT-148 describe in `../querysource` (two
independent fact sheets + a codex second opinion, every load-bearing claim
spot-checked in code); the tenant model was wrong and is corrected under
"Resolved on 2026-09-24 (FEAT-147 / FEAT-148 cross-check)".

---

## Problem Statement

Every A2UI surface ai-parrot emits today is **baked**: the agent runs the
data (pandas, `qs_execute_slug`, a recipe transformer), copies the resulting rows
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

Why now (revised 2026-09-24): the QuerySource side has shipped —
`describe`/`columns`/`vocabulary` (FEAT-148), the `/api/v3/queries/{slug}`
lane and the tenant-scoped slug URLs are in production with QuerySource
5.0.0 — and ai-parrot's `QuerysourceToolkit` (FEAT-558) landed on
2026-09-17. The new Svelte renderer is about to be designed. This document
fixes the wire contract before it does.

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
- **Fetch path: the renderer calls QuerySource directly** with the
  **viewer's JWT** on `POST /api/v3/queries/{slug}` (`QueryHandler`,
  `services.py:245-248`, serves single-query **and** MultiQuery slugs) or,
  when `source.tenant` is set, `POST /api/v1/{tenant}/queries/{slug}`
  (`TenantQueryHandler`, `services.py:387`, which delegates a stored
  `{slug}` to the **single-query** `QueryService`, `handlers/tenant.py:240-245`,
  and only the slug-less collection POST to `QueryHandler`, L246-249 —
  see the MultiQuery bullet). The legacy
  `POST /api/v2/services/queries/{slug}` still answers single-query slugs
  but is not the target of this contract. QuerySource PBAC
  (`slug:execute`, `datasource:use`, `driver:use`) is the authorization.
  ai-parrot-server does not proxy the fetch. The QuerySource base URL is
  renderer configuration; the **tenant is descriptor content** (see the
  tenant bullet below): the renderer builds `/api/v1/{tenant}/queries/{slug}`
  from `source.tenant`, or `/api/v3/queries/{slug}` when it is `null`.
- **Server-side execution is the alternative lane, not the default:** a
  Python executor runs the same descriptor in-process
  (`QuerySlugSource(slug, tenant=source.tenant)` → `QS(slug, conditions,
  tenant=...)`, or `MultiQS(slug, conditions, tenant=...)` when the source
  `is_multiquery`) for `POST .../refresh` (FEAT-492) with the **owner's**
  `PermissionContext` (`build_principal_context`,
  `handlers/ui_surfaces.py:620`), for the HTML lane when no snapshot is
  present, and for scheduled delivery (FEAT-430). **Trust model (revised
  2026-09-24):** an in-process `QS`/`MultiQS` with `request=None` runs
  **no QuerySource PBAC** and uses the trusted service credentials
  (`queries/qs.py:147-165`; FEAT-147 spec L225 keeps programmatic calls on
  the trusted-service model). The owner's `PermissionContext` gates the
  call on the ai-parrot side only (`AuthorizingDataSource`); the tenant
  must come from the descriptor, explicitly — never from
  `build_principal_context`'s `tenant_id`, which defaults to the
  principal (`auth/permission.py:188-202`).
  `UISurfaceRecord.refreshable` becomes `recipe_name is not None or
  has_data_sources`.
- **One descriptor, one Python reference executor, N renderer executors,
  one set of golden fixtures.** ai-parrot ships the Python executor, the
  JSON Schema of the descriptor/DSL and the JSON in/out fixtures. It does
  **not** ship a TypeScript executor for third parties: every renderer
  (`navigator-frontend-next`, and the bundled `ai-parrot-server/ui`, which
  implements its own as one renderer among others) writes its executor
  against the published schema and must pass the same fixtures.
- **Transform DSL v1: ten declarative operations, no code.** `select`,
  `rename`, `filter`, `group_by` (with `sum|avg|count|min|max`), `sort`,
  `limit`, `derive` (arithmetic between columns and constants only),
  `pivot`, `join` (`inner|left`, equality keys, `null` never matches,
  column collisions resolved by prefix, one join per step, between sources
  of the same surface) and `union` (concatenation by matching columns
  across sources; this is how a `MultiQuerySlugSource` is expressed: N
  descriptors plus a `union`). LLM-generated code is **vetoed** in this
  version.
- **Library input shapes are the renderer's job, not the DSL's.** Turning
  rows into ECharts pie pairs, gauge values, etc. happens in the renderer's
  adapter (today `a2ui-chart-adapter.ts`), consistent with viz-core's
  "describe what, never how".
- **`transform` inline is the rule; `transform.ref` is supported in v1** as
  a URL to a TypeScript module served by ai-parrot-server from a static,
  anonymously readable route, versioned (`<name>@<version>.js`) and pinned
  by an `integrity` (SRI) hash carried in the descriptor. `ref` transforms
  are catalogued, never LLM-written. **Governance:** the static directory is
  published per ai-parrot-server release together with a signed manifest
  (`name@version` → integrity); the builder only accepts refs present in
  the manifest; versions are retired by marking them `deprecated` in the
  manifest, never by deleting the file.
- **Only TOOL-origin builders may emit a descriptor.** A `ProducerOrigin.LLM`
  envelope carrying `parrot_data_sources` fails `validate_envelope` with a
  new code, mirroring D10b (`ACTION_NOT_ALLOWED_FOR_LLM`,
  `catalog/__init__.py:617-632`) and the FEAT-473 inline-data guard
  (`INLINE_DATA_NOT_ALLOWED_FOR_LLM`, `catalog/__init__.py:646-661`). The
  descriptor is assembled by a deterministic builder that **always
  executes the slug once** through the Python executor
  (`QuerySlugSource.fetch`): that run supplies the real columns and dtypes
  the axes are validated against, and `locked` comes from the toolkit's
  `forced_conditions`. (`QSourceTool` and its `ToolResult.metadata` were
  hard-cut by FEAT-558 TASK-3255 and are no longer an input.) The LLM
  chooses slug, component, axes and the request; it never types the
  descriptor.
- **Parameters come from the slug's contract, not from the LLM.**
  `params` are derived from FEAT-558 `QuerysourceToolkit.describe_slug`
  (`qs_describe_slug`, `toolkit.py:160`), whose `PlaceholderInfo`
  (`models.py:24-29`: `name`, `type`, `default`) this feature **extends
  with `required` and `accepts_keywords`** by calling QuerySource's own
  `querysource.queries.describe.build_variables(query_raw, conditions,
  cond_definition)` in-process (`queries/describe.py:108`;
  `accepts_keywords = type ∈ KEYWORD_TYPES {date, datetime, timestamp}`
  **or `raw_type is None`**, L29/L163; `required = name ∉ conditions ∧
  name ∉ IMPLICIT_DEFAULTS` — static, so `firstdate`/`lastdate`/
  `filterdate` are never required and default to `current_date`,
  L31-33/L154; `variables` come back as `DescribeVariable` **objects**,
  `.model_dump()` them as `describe_slug` does at L227-229) — the same
  *parsing* as `GET /api/v1/queries/{slug}/describe`, without its
  authorization and redaction (`slug:describe`, `slug:describe_raw`,
  tenant ∈ JWT `programs` pre-filter; `auth/slug_visibility.py:203-206,
  420-431`): the toolkit path is service-trust by design, exactly as
  FEAT-558's `include_sql` already is. Requires `querysource>=5.0.0` (floor bump in
  `packages/ai-parrot-tools/pyproject.toml:77`, today `>=4.5.11`). Relative dates
  use QuerySource's keyword vocabulary as condition **values** (`TODAY`,
  `YESTERDAY`, `FDOM`, `LDOM`, `CURRENT_YEAR`, `CURRENT_MONTH`, `LAST_YEAR`;
  `GET /api/v1/queries/vocabulary`; case-insensitive, resolved as values by
  `resolve_udf_conditions`, `types/validators.pyx:185-209`). **That
  vocabulary is closed** (revised 2026-09-24): no `LAST_WEEK`, no offset
  expression, and the date helpers are `invocable: false` — a linked
  widget can express "yesterday → today", "month to date"
  (`FDOM` → `TODAY`) or "last year", not "last 7 days". There is **no**
  `{today}` placeholder grammar in QuerySource. The
  FEAT-558 dialect's deployment-defined `@variables` (`@today`,
  `dialect.py:207` `load_variables`) are **not** part of the wire: the
  builder rejects any `@`-prefixed condition value, because they are not
  portable across deployments.
- **`locked` conditions are a UX hint only.** A descriptor built from a
  dataset with `permanent_filter` carries those conditions as `locked`
  so the filter bar does not expose them; they are **not** a security
  barrier (a viewer could drop them). Security is QuerySource PBAC plus
  slug design. This must be documented in the wire doc.
- **`conditions` is carried both raw and structured.** `conditions` is
  the exact QuerySource payload the renderer POSTs (the output of the
  toolkit's `build_conditions`, `dialect.py`, minus the toolkit-only
  `querylimit` cap), so an executor needs no knowledge of the dialect. A
  sibling `request` block keeps the toolkit's structured form
  (`placeholders`, `filter`, `fields`, `ordering`, `grouping`, `limit`) so
  a `FilterBar` can edit `filter` entries as well as `params`. The builder
  derives `conditions` from `request` and refuses a descriptor where they
  disagree; an executor that re-fetches after an edit rebuilds
  `conditions` from `request` with the same deterministic rules, which are
  part of the golden fixtures.
- **MultiQuery slugs: public only in v1 (revised 2026-09-24).** A *public*
  `is_multiquery` slug is an ordinary source: the renderer fetches it on
  `POST /api/v3/queries/{slug}` (`QueryHandler` → `MultiQS`,
  `handlers/multi.py:327-343`) and the Python executor dispatches it to
  `MultiQS(slug, conditions, tenant=None)`. A *tenant* MultiQuery slug has
  **no HTTP lane**: `/api/v1/{tenant}/queries/{slug}` delegates to the
  single-query `QueryService` (`handlers/tenant.py:240-245`) and never
  expands the stored pipeline, and v3 has no tenant variant — contrary to
  the FEAT-147 spec's own route table ("Unified stored single/multi
  execution", `sdd/specs/per-tenant-queries.spec.md` ~L186). The builder
  therefore rejects `tenant != null ∧ is_multiquery` with
  `TENANT_MULTIQUERY_UNSUPPORTED`, and a QuerySource bug is filed against
  FEAT-147 to honour its spec; once it lands the rejection is lifted with
  no wire change. The descriptor carries `is_multiquery` so every
  executor dispatches correctly. `build_variables` reports
  `variables_supported=False` only for JSON-dialect `query_raw`, so a
  MultiQuery's `params` are usually empty. `union` remains the way to
  express a DatasetManager `MultiQuerySlugSource` (N independent `QS`
  calls, `sources/query_slug.py:165-260`).
- **The builder always executes once; `snapshot` only decides whether
  the rows are embedded.** Chat: optional, mandatory once persisted. In a
  turn response the agent decides (`snapshot: bool`); when present it is the initial `dataModel`
  (with `snapshot_at`), capped at **500 rows per source** by the builder
  (`max_snapshot_rows`, `snapshot_truncated: true` when cut), and the
  renderer paints it before applying the refresh policy; without it the
  renderer shows a loading state until the first fetch. **At save time**
  (`POST /api/v1/ui/surfaces`, `publish_surface`) the server executes the
  descriptor once with the owner's context if the envelope has sources but
  no snapshot, and persists `dataModel` + `snapshot_at`. Consequently
  `GET` (JSON and HTML) **never executes** anything — `bake_envelope`
  (`baking.py:140`) always finds resolvable bindings — and only
  `POST .../refresh` renews the snapshot.
- **Refresh policy:** `on_mount` by default; `manual` and `interval`
  optional. `interval` is clamped to a **30 s minimum**, paused while the
  document is hidden and resumed with an immediate fetch. The renderer
  keeps "Filter" (local, over embedded rows, §7.4 of the frontend
  reference) distinct from "Refresh" (re-fetch with the current params).
- **FilterBar carries params.** The existing `FilterBar` catalog component
  is extended: a filter may declare `metadata.extensions.parrot_param =
  {"source": "<key>", "name": "<param>"}`; with it a change re-fetches that
  source (Refresh), without it the filter stays local (§7.4). One
  component, one lowering.
- **Share-token viewers** (FEAT-492) whose own credentials are denied by
  QuerySource keep the last server-refreshed snapshot with a "data as of
  `snapshot_at`" notice and a button for the server-side refresh
  (`POST .../refresh`, owner context, which the share token already
  permits). No automatic server refresh on their behalf.
- **Tenant is descriptor content (revised 2026-09-24; was "session
  context").** QuerySource FEAT-147 selects the store **only** from the URL
  path segment (`handlers/tenant.py:230-238` → `request['qs_tenant']`) or
  the keyword-only `tenant=` of `QS`/`MultiQS` (`queries/qs.py:42-51`,
  `multi/__init__.py:96-109`). Nothing derives it from JWT, session or
  headers; no endpoint lists tenants (`TenantRegistry.stores()` is used
  only by the scheduler); names are exact and case-sensitive; and
  `resolve(None)` silently falls back to `public.queries`, so a
  same-named public slug would run *instead of* the tenant's
  (`tenants.py:402-419`). Therefore each source carries
  `tenant: str | null` — the QuerySource store schema, `null` = `public`/
  legacy. It is independent of FEAT-535's `UISurfaceRecord.tenant` (an
  ai-parrot auth scope), which is never used to select a store. FEAT-147
  adds **no tenant-membership check** on execution (spec L54, L226; PBAC
  evaluates the bare slug name, `handlers/abstract.py:551-557`), so
  `tenant` is routing, not security — the same status `locked` has.
- **Never leak SQL.** Descriptors reference slugs only; QuerySource raw
  `query` mode is never allowed on the wire.
- **Additive.** No change to existing envelopes, builders' outputs, the
  A2UI models, renderers or the ui_surfaces DDL beyond what is listed in
  Impact. Baked surfaces keep working exactly as today.
- **Dependencies and sequencing (closed on 2026-09-24):** QuerySource
  **5.0.0** (tag `aebc55c`, 2026-09-16, in production) ships FEAT-148
  `describe`/`columns`/`vocabulary` (`services.py:204-210`, tenant variants
  `:215-219`), the `/api/v3/queries/{slug}` lane and the tenant-scoped
  slug URLs. ai-parrot **FEAT-558 `QuerysourceToolkit`**
  (`querysource-toolkit-refactor`, 11/11 tasks done 2026-09-17) replaced
  the never-created "FEAT-567". Both gates are closed: `/sdd-spec`
  proceeds now. The only sequencing left is the `querysource>=5.0.0`
  floor bump in `packages/ai-parrot-tools/pyproject.toml` (today
  `>=4.5.11`, L77), which is a task of this feature.
- Conventions: Pydantic v2 models, async I/O, `self.logger`, Google
  docstrings, `pytest` + `pytest-asyncio`, golden-file tests
  (`tests/outputs/a2ui/golden/`), conformance registration in
  `tests/outputs/a2ui/conformance/test_all_emitters.py`.

---

## Options Explored

### Option A: Surface-level `parrot_data_sources` extension + TOOL-origin builder + dual DSL executors

Four pieces, all additive:

1. **Descriptor models** (`parrot/outputs/a2ui/linked/models.py`): Pydantic
   `LinkedDataSource` (`kind: "query_slug"`, `slug`, `tenant: str | null`,
   `is_multiquery`, `conditions`,
   `request: {placeholders, filter, fields, ordering, grouping, limit}`,
   `params: {name: {type, default, required, editable, accepts_keywords}}`,
   `locked: [names]`, `transform: TransformSpec | None`, `target` pointer,
   `snapshot_at`, `refresh: {"policy": "on_mount|manual|interval",
   "interval_seconds"}`) and `TransformSpec` (either `ops: [...]` inline or
   `ref: {url, integrity}`), plus the ten `ops` models. JSON Schema is
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
   `build_html_document` precedent, `builders.py:311`). The agent-facing
   tool is **`qs_build_linked_surface`, a new tool on FEAT-558
   `QuerysourceToolkit`** (`parrot_tools/querysource/toolkit.py`): it
   reuses the toolkit's `SlugCatalog`/`TenantGuard` **made tenant-aware**
   (revised 2026-09-24: lookups go through QuerySource's in-process
   `DefinitionRepository.get(QueryIdentity(registry.resolve(tenant), slug))`
   and `.list(store, params)` (`repositories/definitions.py:161,175`)
   instead of `QueryModel` over `public.queries`, which cannot see
   `"{schema}".queries`; the existing `programs` allowlist keeps working
   unchanged because a tenant definition's runtime `program_slug` **is**
   its schema name, `definitions.py:111-119`), `forced_conditions`
   (→ `locked`), `build_conditions` (→ `conditions`) and the extended
   `describe_slug(slug, tenant=None)` (→ `params`), always executes the
   slug once through the Python executor with `tenant=`, and hands the
   frame to the pure builder. No separate `LinkedSurfaceToolkit`; a
   DatasetManager wrapper is a follow-up, not v1.
3. **Python executor** (`parrot/outputs/a2ui/linked/executor.py` +
   `dsl.py`): fetch through `QuerySlugSource.fetch(**conditions)`
   (`sources/query_slug.py:122`), apply the DSL over a `pandas.DataFrame`,
   write into `dataModel[target]`. Wired into `UISurfacesHandler._refresh`
   as a second path next to `RecipeRunner`, and into the save path
   (`_pin_save` / `publish_surface`) to produce the snapshot when a linked
   envelope arrives without one. `GET` lanes never execute. `refreshable`
   widened. `PublishSurfaceTool` reports `refreshable` accordingly.
4. **Published contract for renderers + the bundled UI's own executor**:
   ai-parrot publishes the descriptor/DSL JSON Schema and the golden
   fixtures (`tests/outputs/a2ui/golden/linked/`), and ai-parrot-server
   serves `ref` transforms from a static route with a signed manifest.
   `navigator-frontend-next` implements its executor from that contract.
   The bundled `ai-parrot-server/ui` implements **its own** executor as one
   more renderer (not a reference for anyone): `a2ui-types.ts` gains
   `CreateSurface.metadata`; a `linked/` module (fetch via
   `POST /api/v3/queries/{slug}` — or `/api/v1/{tenant}/queries/{slug}`
   when `source.tenant` is set — with the viewer's bearer, DSL
   executor, refresh scheduler, `ref` loader with SRI check) and an
   insertion point in `A2UISurface.svelte` (today a stateless renderer
   with no fetch, `A2UISurface.svelte:12-30`); `FilterBar` gets a branch
   in `A2UINode.svelte` honouring `parrot_param`.

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
- Several executors of the same DSL (Python reference plus one per
  renderer) must stay in parity; the golden fixtures are the contract and
  they must be maintained with every DSL change.
- Net-new frontend surface: the bundled UI has no API client for
  QuerySource or ui_surfaces at all (`grep` → 0 hits in `ui/src`), so its
  lane is written from scratch.
- Viewer-credential fetch means a shared surface (FEAT-492 share token)
  may render the snapshot but fail to refresh for a viewer without
  `slug:execute`; the renderer degrades to snapshot + notice + server-side
  refresh button.
- Saving a linked envelope without a snapshot makes `POST /api/v1/ui/surfaces`
  execute the slug (owner context) — a write with a data-plane side effect,
  bounded to save and refresh only.
- Surface-level validation is a new concept in `validate_envelope`.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` v2 | descriptor + DSL models, JSON Schema export | already the wire model stack |
| `pandas` | Python DSL executor over `QuerySlugSource.fetch()` DataFrames | already a core dependency (DatasetManager) |
| `querysource` (in-process `QS`) | server-side fetch | already used by `QuerySlugSource` (`lazy_import`, `sources/query_slug.py`) |
| `jsonschema` | validate `parrot_data_sources` in the conformance suite | already used by `catalog.validate_message` |
| Svelte 5 + TypeScript | the bundled UI's own renderer lane in `ai-parrot-server/ui` | existing bundled UI stack; not a reference for `navigator-frontend-next` |
| `aiohttp` static route | serve `ref` transform modules + signed manifest | already the server stack; SRI hash in descriptor |

🔗 **Existing Code to Reuse:**
- `parrot/outputs/a2ui/builders.py:69` `build_surface` (needs `surface_metadata`), `:116` `build_chart`, `:137` `build_kpicard`, `:179` `build_datatable`, `:311` TOOL-origin precedent in `build_html_document`.
- `parrot/outputs/a2ui/catalog/__init__.py:499` `validate_envelope`; `:617-632` D10b gate; `:646-661` inline-data gate; `catalog/base.py:78-86` error codes; `base.py:89-98` `ProducerOrigin`.
- `parrot/outputs/a2ui/models.py:446-470` `CreateSurface` (surface `metadata`), `:338-378` `Extensions`/`SurfaceMetadata`.
- `parrot/outputs/a2ui/baking.py:356` `bake_envelope`, `:187-191` `parrot_optional`, `:140` `BakeError`.
- `parrot/outputs/a2ui/recipes/models.py:69` `DataSourceSpec`, `:90` `TransformStep`, `:51` `RecipeParam`; `recipes/params.py:30-39` `DATE_RESOLVERS`/`resolve_date` (the in-house relative-date precedent, to be superseded by QuerySource keywords for linked sources).
- `parrot/tools/dataset_manager/sources/query_slug.py:36-162` `QuerySlugSource` (`fetch`, `cache_key`, `permanent_filter` wins); `tool.py:966` `add_dataset`; `:60` `DatasetInfo`; `:2766` `list_datasets`.
- `parrot_tools/querysource/toolkit.py:59` `QuerysourceToolkit` (`describe_slug` L160, `execute_slug` L190, `_open`/`SlugCatalog` L113-117, `forced_conditions` L88); `models.py:24-45` `PlaceholderInfo`/`SlugDetail`, `:47-59` `ExecutionResult`; `dialect.py` `build_conditions`/`validate_placeholders`/`validate_filter`, `load_variables` L207; `catalog.py:39-55` `SlugRecord` (`conditions`, `cond_definition`, `query_raw`), `:97` `TenantGuard`, `:131` `SlugCatalog.get_allowed`.
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

What A trades off, knowingly: a DSL that must be kept in parity across the
Python reference and every renderer's executor (mitigated by the published
JSON Schema, the shared golden fixtures and a small, closed operation set),
and the fact that this repo does not ship a TypeScript executor for third
parties — the production renderer lives in `navigator-frontend-next` and
implements its own; the bundled UI implements one as well, for itself.

---

## Feature Description

### User-Facing Behavior

**For the agent author / LLM.** Given an agent with the FEAT-558
`QuerysourceToolkit` (a `programs` allowlist, optional
`forced_conditions`), a request like "make me a weekly field
activity widget" produces:

1. The LLM explores with `qs_list_slugs` / `qs_describe_slug` /
   `qs_execute_slug` and chooses the component and axes from the **real**
   columns returned.
2. It calls `qs_build_linked_surface` with the `slug`, the structured
   `request` (`placeholders`, optional `filter`/`fields`/`ordering`/
   `grouping`/`limit`), the component descriptor and `snapshot: true|false`.
   The tool checks the tenant allowlist, calls the extended
   `describe_slug` for the parameter contract, builds `conditions` from
   `request` (+ `forced_conditions` → `locked`; `@`-values rejected),
   **executes the slug once** through the Python executor to validate the
   axes against real columns and dtypes, and emits the envelope with
   `origin=TOOL` — embedding the (≤500-row) rows only when `snapshot` is
   true.
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
          "tenant": null,
          "is_multiquery": false,
          "conditions": {"firstdate": "YESTERDAY", "lastdate": "TODAY", "program": "epson"},
          "request": {"placeholders": {"firstdate": "YESTERDAY", "lastdate": "TODAY", "program": "epson"},
                      "filter": {}, "fields": [], "ordering": [], "grouping": [], "limit": null},
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
`POST /api/v3/queries/epson_field_activity` (or, when `source.tenant` is
set, `/api/v1/{tenant}/queries/epson_field_activity`) with the descriptor's `conditions` and the viewer's bearer
token, runs the transform, writes the
rows to `/activity/rows`, and re-renders. Editable params drive a filter
bar (date pickers accept keywords such as `FDOM`); "Refresh" re-fetches
with the current params; "Filter" stays local over the embedded rows;
"Reload without cache" adds `refresh: true` to the conditions
(QuerySource's own cache bypass — boolean `true`, never a string:
QuerySource applies `bool()` to the raw value, `providers/abstract.py:83-85`;
the result cache is keyed per store schema + definition revision,
`cache_identity.py:65-94`, so tenants never share entries). `locked` params are shown read-only.
A fetch answered **404** keeps the snapshot on screen with a non-blocking
notice worded "unavailable", never "denied": QuerySource deliberately
answers 404 for PBAC denial, unknown tenant, missing slug *and* missing
session alike — no 403 exists (`handlers/abstract.py:361-568`,
`handlers/tenant.py:137-165`); without a snapshot the widget shows an
"unavailable" message.

**For persistence (FEAT-492).** "Pin" saves the envelope; if it carries
sources but no snapshot, the server executes the descriptor once (owner
context) and stores the snapshot with it, so every persisted linked surface
has one. The surface is `refreshable` because it has data sources; `POST
/api/v1/ui/surfaces/{id}/refresh` (owner context, share tokens included)
runs the Python executor, updates `dataModel` and `snapshot_at` in place,
and answers negotiated JSON/HTML. `GET` (JSON or `?format=html`) only reads.

**For a share-token viewer.** The snapshot renders; the on-mount fetch runs
with the viewer's own credentials. If QuerySource denies it, the snapshot
stays with a "data as of `snapshot_at`" notice and a "Refresh on server"
button that calls `POST .../refresh`.

**For a dashboard.** Two slugs → two entries under `parrot_data_sources`
(each with its own params and refresh policy) → KPI cards, charts and a
`DataTable` bound to either; a `join` step in one source's transform may
reference the other source by key, and a `union` concatenates sources with
matching columns (how a `MultiQuerySlugSource` is expressed). Filters in a
`FilterBar` that declare `parrot_param` re-fetch their source; the others
filter locally.

**`transform.ref`.** `{"ref": {"url": "/static/a2ui/transforms/group_by_day@1.0.0.js",
"integrity": "sha384-…"}}` loads a catalogued module served by
ai-parrot-server (anonymous read); the renderer refuses to execute on
integrity mismatch and falls back to the snapshot.

### Internal Behavior

1. **Models and schema.** `LinkedDataSource`, `TransformSpec`, the ten op
   models and `RefreshPolicy` as Pydantic v2 in
   `parrot/outputs/a2ui/linked/models.py`; `export_json_schema()` writes
   the schema published for renderers and used by the conformance suite.
   `interval_seconds` validates `>= 30`.
2. **Validation.** `validate_envelope` grows a surface-level pass: parse
   `metadata.extensions.parrot_data_sources` into the models; every
   `target` must be an absolute pointer whose root key exists in
   `dataModel` **or** is referenced by at least one binding; `locked` ⊆
   `params`; `join.with` must name another source of the same surface;
   `kind` ∈ {`query_slug`}; `transform.ref` must match an entry of the
   transforms manifest; `origin is LLM` → `DATA_SOURCES_NOT_ALLOWED_FOR_LLM`.
   Issues are reported all at once, like today.
3. **Builder.** `build_surface(..., surface_metadata=SurfaceMetadata | None)`;
   `build_linked_surface(components, sources, *, snapshot, surface_id)`
   validates `x`/`y`/`columns` props against the columns **and dtypes** of
   the frame the executor just fetched (the builder is pure: it receives
   `LinkedDataSource` objects plus their frames), sets
   `origin=ProducerOrigin.TOOL`, and returns `CreateSurface`.
4. **Agent tool** (`QuerysourceToolkit.build_linked_surface` →
   `qs_build_linked_surface`, `parrot_tools/querysource/toolkit.py`;
   FEAT-558 modified): `await self._catalog.get_allowed(slug, tenant=tenant)`
   first (program/tenant gate, as `execute_slug` does at L207 —
   `get_allowed`, `describe_slug`, `execute_slug` and `list_slugs` gain
   `tenant: str | None`, resolved through `DefinitionRepository`); the extended
   `describe_slug` (`PlaceholderInfo` + `required`/`accepts_keywords` via
   `querysource.queries.describe.build_variables`) → `params`;
   `validate_placeholders` + `build_conditions(..., forced=
   self.forced_conditions)` → `conditions`, forced keys → `locked`,
   `@`-values rejected; **always** runs the Python executor once
   (`QuerySlugSource.fetch`, not capped by the toolkit's `max_rows`) to
   validate the axes and, when `snapshot=True`, embeds ≤500 rows
   (`max_snapshot_rows`, `snapshot_truncated`); returns the envelope in
   the same shape `structured_chart` responses use (`a2ui_envelope` +
   `artifacts[]`, FEAT-473 dual emission). Multi-slug surfaces
   (`MultiQuerySlugSource`-style) take a list of sources plus a `union`
   step.
5. **Python executor** (`linked/executor.py`, `linked/dsl.py`): for each
   source, merge `conditions` with call-time param overrides (locked keys
   cannot be overridden), fetch through `QuerySlugSource(slug, tenant=source.tenant).fetch(**conds)`
   (a new `tenant` pass-through to `QS(..., tenant=)`; `is_multiquery`
   sources go to `MultiQS(..., tenant=)`) under the caller's
   `PermissionContext` (ai-parrot-side gate via `AuthorizingDataSource`
   when a guard is configured — QuerySource itself runs no PBAC
   in-process), apply the DSL over the DataFrame, write to
   `dataModel[target]` (`orient="records"`), stamp `snapshot_at`. `join`
   pulls the other source's already-executed frame. Pure functions; no LLM.
6. **ui_surfaces integration.** `UISurfaceRecord.refreshable` →
   `recipe_name is not None or _has_data_sources(envelope)`; `_refresh`
   dispatches on which one is present (recipe first when both), passes
   each source's `tenant` explicitly (never `build_principal_context`'s
   defaulted `tenant_id`) and maps `TenantError.error_code` to 404/503;
   the save
   path (`_pin_save`, `publish_surface`) executes the descriptor with the
   owner's context when a linked envelope has no snapshot and persists the
   result; `GET`/HTML negotiation never executes; `PublishSurfaceTool`
   returns `refreshable` from the record.
7. **Static transforms route + manifest.** ai-parrot-server serves
   `/static/a2ui/transforms/<name>@<version>.js` from a directory published
   per release, anonymous, immutable cache headers, plus a signed
   `manifest.json` (`name@version` → integrity, `deprecated` flag). The
   builder embeds the integrity from the manifest and rejects unknown refs.
8. **Bundled UI executor** (`ai-parrot-server/ui`, its own renderer lane):
   `a2ui-types.ts` adds `metadata?: {extensions?: Record<string, unknown>}`
   to `CreateSurface`; `linked/` module = descriptor parsing,
   `fetchSource()` (QuerySource client → `POST /api/v3/queries/{slug}` or
   `/api/v1/{tenant}/queries/{slug}`, bearer from `auth-headers.ts`, tenant
   from `source.tenant`), `applyTransform()` (DSL executor),
   `RefreshScheduler` (30 s clamp, `visibilitychange` pause/resume),
   `loadRef()` with SRI; `A2UISurface.svelte` becomes stateful over
   `dataModel` and mounts the lane when `parrot_data_sources` is present;
   `A2UINode.svelte` gains a `FilterBar` branch honouring `parrot_param`.
   Its tests load the Python `golden/linked/` fixtures.
9. **Docs.** `parrot_data_sources` and `parrot_param` rows in the
   `docs/outputs/a2ui-v1.md` extension table; a new section in the
   frontend reference (§6.5 linked surfaces, executor contract = schema +
   fixtures; §7.4 amended: Filter vs Refresh vs Reload).

### Edge Cases & Error Handling

- **LLM-origin envelope with a descriptor** → `validate_envelope` issue
  `DATA_SOURCES_NOT_ALLOWED_FOR_LLM`; the producer retry loop sees it
  like an action violation.
- **Slug unknown / viewer denied at fetch time** → renderer keeps the
  snapshot and shows a notice; server-side refresh maps QuerySource's `TenantError.error_code`
  (`tenant_not_available` → 404, `query_not_found` → 404,
  `tenant_store_unavailable` → 503; `tenant_errors.py`, `tenants.py:422-425`,
  `repositories/definitions.py:165-169`) and only other `RuntimeError`s
  from `QuerySlugSource.fetch` to `502` (data stage) like the recipe path.
- **Save without snapshot** → the save path executes the descriptor; on
  failure the save answers `502` (data stage) with the same envelope as the
  refresh path and nothing is persisted. `GET` lanes never execute, so an
  HTML render always has a snapshot.
- **Locked key overridden in a refresh request** → ignored with a warning
  in the response (`ignored_params`).
- **Transform errors** (missing column, type mismatch in `derive`, join key
  absent) → the executor fails the *source*, not the surface: other sources
  still render; the failed target keeps its snapshot and the error is
  reported in `dataModel["_linked"]["errors"]` (renderer) / response
  `warnings` (server).
- **`ref` integrity mismatch or fetch failure** → transform skipped,
  snapshot shown, error surfaced; never executes unverified code.
- **Interval policy** → 30 s minimum enforced by both the model validator
  and the renderer; paused on `document.hidden`, immediate fetch on resume.
- **Relative-date keywords in a typed `date` param** are supported by
  QuerySource ≥ 5.0.0 (FEAT-148 UDF fix); against an older QuerySource
  (`check_version_compatibility`, `dialect.py`) the builder emits absolute
  dates and marks `accepts_keywords: false`. A `@variable` value (FEAT-558
  dialect) anywhere in `request` is rejected at build time with a clear
  error.
- **Large results** → the DSL executor works in memory; the builder caps
  a *snapshot* at 500 rows per source (`max_snapshot_rows`) with
  `snapshot_truncated: true` (the live fetch is not capped; QuerySource
  `querylimit` may be part of `conditions`).
- **Share-token viewers** (FEAT-492) fetch with their own credentials; if
  denied they see the last server-refreshed snapshot with a notice and a
  server-side refresh button (owner context); no automatic server refresh.
- **Multi-tenant deployments** → each source carries its `tenant`; the
  renderer builds the tenant URL from it and the executor passes it to
  `QS`/`MultiQS`; a tenant that no longer resolves → QuerySource 404 /
  `TenantError(tenant_not_available)` → snapshot kept with an
  "unavailable" notice. A tenant is never inferred: a source with
  `tenant: null` runs against `public.queries`, by design.
- **`ref` not in manifest / deprecated** → builder refuses at build time;
  a renderer meeting a deprecated ref still executes it (integrity holds)
  and logs a deprecation warning.

---

## Capabilities

### New Capabilities
- `a2ui-linked-data-sources`: the `parrot_data_sources` surface extension, its Pydantic/JSON-Schema models, surface-level validation and the TOOL-origin gate.
- `a2ui-transform-dsl`: the ten-operation declarative DSL (incl. `join` and `union`) with the Python reference executor, the published JSON Schema and the golden fixtures every renderer executor must pass; `transform.ref` static module serving with SRI and a signed manifest.
- `linked-surface-builder`: `build_linked_surface` + `surface_metadata` on `build_surface`; `qs_build_linked_surface` on `QuerysourceToolkit` (tenant gate, `request` → `conditions`, `forced_conditions` → `locked`, extended `describe_slug` → `params`, one mandatory execution, 500-row snapshot cap; N sources + `union` for multi-slug surfaces).
- `linked-surface-python-executor`: server-side fetch + transform behind FEAT-492 refresh and the save path (snapshot on pin/publish); tenant-aware (`QuerySlugSource(tenant=)`, `QS`/`MultiQS` dispatch by `is_multiquery`), trusted-service credentials, `TenantError` mapping.
- `a2ui-linked-bundled-ui-lane`: the bundled UI's own executor (QuerySource client, DSL, refresh scheduler with 30 s clamp, `FilterBar` `parrot_param`, share-denied degradation).

### Modified Capabilities
- `a2ui-surface-rehydration` (FEAT-492, `sdd/specs/a2ui-surface-rehydration.spec.md`): `refreshable` widened; `_refresh` gains the descriptor path; the save path produces the snapshot when missing; `GET` never executes.
- `querysource-toolkit-refactor` (FEAT-558, `sdd/specs/querysource-toolkit-refactor.spec.md`): `PlaceholderInfo` gains `required`/`accepts_keywords` (via `build_variables`); `SlugCatalog` becomes tenant-aware over `DefinitionRepository` and `describe_slug`/`execute_slug`/`list_slugs` gain `tenant`; new `build_linked_surface` tool; `querysource>=5.0.0` floor.
- `a2ui-v1-dialect` (FEAT-470): new extension keys (`parrot_data_sources`, `parrot_param`) documented; `validate_envelope` gains a surface-level pass and a new error code.
- `a2ui-v1-structured-outputs` (FEAT-473): linked envelopes emitted with the same dual-emission shape.
- `html-renderer-design-system` (FEAT-493, `FilterBar`): filters may carry `parrot_param` (re-fetch) next to local filtering.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/outputs/a2ui/linked/` (`models.py`, `dsl.py`, `executor.py`, `schema.py`) | new | descriptor + DSL models, executors, JSON Schema export |
| `parrot/outputs/a2ui/builders.py` | extends | `surface_metadata` on `build_surface`; `build_linked_surface` |
| `parrot/outputs/a2ui/catalog/__init__.py`, `catalog/base.py` | extends | surface-level validation pass; `DATA_SOURCES_NOT_ALLOWED_FOR_LLM` |
| `parrot/outputs/a2ui/models.py` | none | `CreateSurface.metadata` already exists |
| `parrot/outputs/a2ui/baking.py` | none | snapshot resolves bindings; no-snapshot handled by callers |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py`, `models.py`, `dialect.py` | extends | `build_linked_surface` tool (`qs_build_linked_surface`); `PlaceholderInfo.required/accepts_keywords`; `@`-value rejection helper; tenant-aware `SlugCatalog` over `DefinitionRepository`; `tenant` on describe/execute/list |
| `packages/ai-parrot-tools/pyproject.toml` | modifies | `querysource>=5.0.0` floor (L77, today `>=4.5.11`) |
| `parrot/tools/dataset_manager/sources/query_slug.py` | extends | `QuerySlugSource(slug, tenant=None)` → `QS(..., tenant=)`; `is_multiquery` → `MultiQS(..., tenant=)` |
| QuerySource FEAT-147 follow-up (`../querysource`; bug vs its own route table) | depends on (non-blocking) | tenant `{slug}` route must dispatch stored MultiQuery to `QueryHandler`/`MultiQS`; until then the builder rejects tenant MultiQuery sources |
| `packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py` | modifies | `refreshable` from record instead of `recipe_name is not None` |
| `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py` | modifies | `refreshable` property |
| `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py` | extends | descriptor refresh path; snapshot production on save when missing; `GET` untouched |
| `parrot/outputs/a2ui/catalog/parrot/filterbar.py` | extends | `parrot_param` extension on filters (schema + lowering pass-through) |
| ai-parrot-server static route + signed manifest for `ref` transforms | new | `/static/a2ui/transforms/<name>@<ver>.js` + `manifest.json`, anonymous, SRI, `deprecated` flag |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/` (`a2ui-types.ts`, `A2UISurface.svelte`, `A2UINode.svelte`, new `linked/`) | extends / new | the bundled UI's own executor lane |
| `packages/ai-parrot-server/ui/src/lib/api/` | new | QuerySource client (`services/queries`) with bearer |
| `tests/outputs/a2ui/golden/linked/`, `tests/outputs/a2ui/conformance/test_all_emitters.py` | new / extends | DSL fixtures (shared with TS tests); conformance registration of `build_linked_surface` |
| `docs/outputs/a2ui-v1.md`, `docs/frontend/agentdashboard-a2ui-reference.md` | modifies | extension table; §6.5 linked surfaces; §7.4 Filter/Refresh/Reload |
| FEAT-558 `QuerysourceToolkit` (done 2026-09-17) | depends on / modifies | host of the agent tool; `describe_slug` extension |
| QuerySource 5.0.0 (FEAT-148 describe, `/api/v3/queries/{slug}`, `/api/v1/{tenant}/queries/{slug}`) | depends on | in production; in-process `querysource.queries.describe.build_variables` |
| `navigator-frontend-next` (external) | consumer | production renderer; implements its own executor from the published JSON Schema + golden fixtures (no TS shipped from this repo) |

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

# From packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py  (FEAT-558; verified 2026-09-24)
class QuerysourceToolkit(AbstractToolkit):                                     # L59; tool_prefix "qs" L67
    def __init__(self, programs=None, allow_write=False, allow_raw_sql=False, allow_external_sources=True,
                 include_sql=True, max_rows=200, forced_conditions=None, dsn=None,
                 multiquery_timeout=600.0, **kwargs)                            # L73-84
    async def _open(self) -> None   # SlugCatalog(dsn or _qs.default_dsn(), TenantGuard)   # L113-117
    async def describe_slug(self, slug: str, dry_run: bool = False) -> SlugDetail   # L160
        # PlaceholderInfo(name=n, type=rec.cond_definition.get(n), default=rec.conditions.get(n))  L166-169
    async def execute_slug(self, slug, placeholders=None, filter=None, fields=None, ordering=None,
                           grouping=None, limit=None, offset=None, refresh=False) -> ExecutionResult  # L190-200
        # get_allowed(slug) L207 → validate_placeholders L209 → validate_filter L210
        # → build_conditions(..., max_rows=self.max_rows, forced=self.forced_conditions) L211-222
        # → QS(slug=slug, conditions=conditions).query(output_format="pandas") L226-228 → frame_to_result L241
# models.py: PlaceholderInfo(name, type: str | None, default: Any)  L24-29  — NO required / accepts_keywords
#   SlugDetail(SlugSummary): placeholders_detail, filtering, fields, ordering, grouping, is_cached,
#     cache_timeout, sql, pipeline, rendered_query  L32-45
#   ExecutionResult(status, slug, rows, returned_rows, total_rows, truncated, columns,
#     applied_conditions, rejected_inputs, duration_ms)  L47-59  — NO dtypes
# dialect.py: build_conditions(...), validate_placeholders(...), validate_filter(...);
#   load_variables() -> dict[str, str]  ('@name' → doc; QUERYSOURCE_VARIABLES / QS_VARIABLES)  L207
# catalog.py: SlugRecord(slug, program_slug, description, provider, is_cached, cache_timeout, conditions,
#   cond_definition, filtering, fields, ordering, grouping, query_raw, pipeline)  L39-55;
#   TenantGuard L97; SlugCatalog L131 (get_allowed raises SlugNotFoundError / TenantDeniedError)

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
from parrot_tools.querysource.toolkit import QuerysourceToolkit                                      # parrot_tools/querysource/toolkit.py:59
from parrot_tools.querysource.models import PlaceholderInfo, SlugDetail, ExecutionResult            # parrot_tools/querysource/models.py
from parrot_tools.querysource.dialect import build_conditions, validate_placeholders, load_variables # parrot_tools/querysource/dialect.py
from querysource.queries.describe import build_variables, KEYWORD_TYPES                              # ../querysource ≥ 5.0.0, queries/describe.py:29,108
from querysource.queries.multi import MultiQS                                                        # ../querysource, multi/__init__.py:56; tenant= kw L96-109
from querysource.tenants import QueryIdentity, TenantError                                           # ../querysource, tenants.py:34-42, 422
from querysource.repositories.definitions import DefinitionRepository                                # ../querysource, definitions.py:56 (get L161, list L175)
from parrot_tools.ui_surfaces import PublishSurfaceTool                                              # parrot_tools/ui_surfaces.py:60
from parrot.handlers.models.ui_surfaces import UISurfaceRecord, UISurfaceKind                        # ai-parrot-server
```

#### Key Attributes & Constants
- `DEFAULT_CATALOG_ID` → `https://parrot.dev/catalogs/v1` (every public builder sets it).
- `_STRUCTURED_INLINE_DATA_COMPONENTS = {"Chart", "DataTable", "Map"}`, `_STRUCTURED_INLINE_DATA_FIELDS = ("data", "datasets")` (`catalog/__init__.py:105-109`) — the LLM-origin inline-data guard the descriptor gate mirrors.
- `_RESERVED_EXTENSION_PREFIX = "a2ui_"` (`models.py:338`); `parrot_*` keys documented at `docs/outputs/a2ui-v1.md:150-156` (`parrot_role`, `parrot_variant`, `parrot_component_id`, `parrot_optional`, `parrot_unit`, `parrot_trend`, `parrot_series_data`).
- `RecipeRunner.run(name, *, params=None, pctx=None, recipe_owner=None, include_envelope=False) -> RenderedArtifact` (`tools/infographic_recipes/runner.py:243`); `include_envelope=True` ⇒ `artifact.metadata["source_envelope"]` (L271-274); falsy `pctx` ⇒ DatasetManager guards fail **open** (L262-264).
- FEAT-492 refresh precedence: request params > stored `recipe_params` > recipe defaults (`handlers/ui_surfaces.py:604`).
- QuerySource facts (re-verified in `../querysource` at tag 5.0.0 = `aebc55c`, 2026-09-24): `POST /api/v3/queries/{slug}` (`services.py:245-248`, `QueryHandler` `handlers/multi.py:25`, `MultiQS` L335 — single and MultiQuery slugs); `POST /api/v1/{tenant}/queries/{slug}` (`services.py:387`, `TenantQueryHandler` `handlers/tenant.py:142`; a stored `{slug}` goes to the single-query `QueryService` L240-245, only the slug-less POST goes to `QueryHandler` L246-249); no `/api/v3/{tenant}/…` variant; legacy `POST /api/v2/services/queries/{slug}` (`services.py:183`); **FEAT-147 tenant model (verified 2026-09-24):** tenant selected only from the path (`tenant.py:230-238` → `request['qs_tenant']`) or the keyword-only `tenant=` on `QS.__init__` (`queries/qs.py:42-51`; lookup `repo.registry.resolve(self._tenant_selector)` + `QueryIdentity(store, slug)` + `repo.get(identity)`, L173-177) and `MultiQS.__init__` (`multi/__init__.py:96-109`); `TenantRegistry.resolve(None)` → `public.queries`, literal `public` too, unknown → `TenantError(tenant_not_available)` (`tenants.py:402-425`); tenant definitions live in `"{schema}".queries` **without** `program_slug` (`repositories/definitions.py:121-126`, discovery `tenants.py:198-206`), runtime `program_slug` = schema (`definitions.py:111-119`); `DefinitionRepository.get(QueryIdentity)` L161, `.list(store, params) -> DefinitionPage` L175; no membership check on execution, PBAC on the bare slug name (`handlers/abstract.py:551-557`); every execution denial is 404 — no 403 in the codebase; in-process `request=None` ⇒ no PBAC, service credentials (`qs.py:147-165`); result-cache key = `qs:r2:sha256(namespace, schema, table, slug, revision, provider_checksum)` (`cache_identity.py:65-94`); `refresh = bool(conditions.pop('refresh'))` (`providers/abstract.py:83-85`); FEAT-147 shipped in tag 5.0.0 (merge `9eba837`, fix `dd87759`); describe routes `GET /api/v1/queries/describe`, `/{slug}/describe`, `/{slug}/columns`, `/vocabulary` (`services.py:204-210`) + tenant variants (`:215-219`, `handlers/describe.py`); `DescribeVariable(name, type, raw_type, default, required, source, accepts_keywords)` (`queries/describe.py:41-51`); `build_variables(query_raw, conditions, cond_definition) -> {variables, variables_supported, structural_placeholders, warnings}` (L108-111; `variables_supported=False` for JSON-dialect slugs; `variables` are `DescribeVariable` **objects**, L227-229; `required = name ∉ conditions ∧ name ∉ IMPLICIT_DEFAULTS` L154; `accepts_keywords = type ∈ KEYWORD_TYPES or raw_type is None` L163); describe responses nest `variables`/`links`/`warnings`/`capabilities`/`effective_cond_definition` under `derived` plus a `redacted` list (L246-260; `docs/DESCRIBE_API.md` L68-126 example is inaccurate — code is authoritative); vocabulary = exactly 7 keywords, case-insensitive (`types/validators.pyx:27-40`, `utils/vocabulary.py:170-211`, helpers `invocable: false`); describe denial/missing = body-less 404, no principal = 401 (`handlers/describe.py:75-81,93-143`); tenant describe requires tenant ∈ JWT `programs` (`auth/slug_visibility.py:203-206`); `KEYWORD_TYPES = {date, datetime, timestamp}` (L29); `IMPLICIT_DEFAULTS` firstdate/lastdate/filterdate → `current_date` (L31-33); `refresh` popped from conditions to bypass the result cache (`providers/abstract.py:78-82`); keyword vocabulary `UDF_LIST = [CURRENT_YEAR, CURRENT_MONTH, TODAY, YESTERDAY, LAST_YEAR, FDOM, LDOM]` resolved as condition **values** (`rust/src/validators.rs:20-35`, `types/validators.pyx:552-553`); `cond_definition` types (case-insensitive) `literal|int|integer|float|numeric|decimal|epoch|boolean|string|varchar|field|date|datetime|timestamp|uuid|array|json` (`rust/src/validators.rs:280-305`); planned `GET /api/v1/queries/{slug}/describe`, `/{slug}/columns`, `/vocabulary` (`../querysource/sdd/proposals/describe-queryslug.brainstorm.md`).
- Golden convention: `json.dumps(tree.model_dump(mode="json", exclude_none=True), sort_keys=True, indent=2)` byte-equal to `tests/outputs/a2ui/golden/*.json` (`test_components_filterbar.py:15-42`); conformance helper `_assert_conformant(envelope, *, origin=ProducerOrigin.TOOL)` (`conformance/test_all_emitters.py:115`).
- Ledger: `sdd/tasks/.id_ledger.json` → `next_feature_id: 597`, `next_task_id: 3675` (2026-09-24).

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
- ~~FEAT-567 / `qs_describe` / `qs_columns` / `qs_vocabulary` / `qs_run`~~ — FEAT-567 was never created; the toolkit shipped as **FEAT-558 `QuerysourceToolkit`** with tools `qs_get_dialect_reference`, `qs_list_slugs`, `qs_describe_slug`, `qs_execute_slug`, `qs_list_components`, `qs_validate_pipeline`, `qs_run_multiquery`, `qs_save_multiquery` (2026-09-24).
- ~~`QSourceTool`, `parrot_tools/qsource.py`, `ToolResult.metadata["dtypes"]`~~ — hard-cut by FEAT-558 TASK-3255; 0 hits in `packages/*/src` (2026-09-24).
- ~~`PlaceholderInfo.required`, `PlaceholderInfo.accepts_keywords`, `ExecutionResult.dtypes`~~ — absent (`models.py:24-59`); the first two are added by this feature.
- ~~`qs_build_linked_surface`, `LinkedSurfaceToolkit`, `parrot_tools/linked_surfaces.py`~~ — net-new (the second two are NOT built; superseded on 2026-09-24).
- ~~`/api/v3/{tenant}/queries/{slug}`~~ — only `/api/v1/{tenant}/queries/{slug}` exists (`services.py:387`), and it serves single-query slugs only.
- ~~`QuerySlugSource(tenant=...)`, `MultiQuerySlugSource(tenant=...)`~~ — no tenant parameter today (`sources/query_slug.py:51-56,175`); `QS` is built without `tenant` (L152).
- ~~`SlugCatalog` seeing tenant stores~~ — it reads `public.queries` via `QueryModel` only (`catalog.py:132-187`); FEAT-558's `TenantGuard` is a `program_slug` allowlist, not a FEAT-147 store selector.
- ~~A tenant HTTP lane for stored MultiQuery slugs~~ — none (see the MultiQuery bullet); QuerySource bug to file.
- ~~Tenant discovery endpoint, tenant in JWT/session, tenant-membership check on execution~~ — none in QuerySource 5.0.0.
- ~~`LAST_WEEK` / offset keywords, invocable date helpers~~ — the vocabulary is closed at 7 keywords.
- ~~403 from QuerySource execution or describe routes~~ — every denial is 404 (describe: 401 only when there is no principal).
- ~~`{today}` / `{fdom}` placeholder grammar in QuerySource~~ — keywords are condition values, not placeholders.
- ~~`x-parrot-*` descriptors consumed by the A2UI renderer~~ — `x-parrot-rest` exists only in `packages/parrot-formdesigner` (shape precedent, not reusable code).
- ~~`QS.get_definition()`~~ — only `BaseProvider.get_definition()` in QuerySource.

---

## Parallelism Assessment

- **Internal parallelism**: high. Five strands are independent until integration: (1) descriptor + DSL models + JSON Schema + Python DSL executor with golden fixtures; (2) builder + `surface_metadata` + surface-level validation + conformance registration; (3) FEAT-558 toolkit changes in `parrot_tools/querysource` (`PlaceholderInfo` extension, tenant-aware `SlugCatalog` over `DefinitionRepository`, `tenant` on describe/execute/list, `build_linked_surface` tool, floor bump; unblocked) plus the `QuerySlugSource(tenant=)` pass-through in core; (4) ui_surfaces refresh/save integration + static `ref` route and signed manifest (server package); (5) the bundled UI's own executor lane (validated against the same fixtures). Docs last.
- **Cross-feature independence**: no in-flight ai-parrot spec touches `outputs/a2ui/linked/` or the builders' surface metadata. Shared files: `handlers/ui_surfaces.py` and `handlers/models/ui_surfaces.py` (FEAT-535 visibility landed; FEAT-492 complete), `catalog/__init__.py` (any concurrent catalog work), `a2ui-types.ts`/`A2UISurface.svelte` (FEAT-527 bundled-UI work, complete). External dependencies: none open — QuerySource 5.0.0 is in production and FEAT-558 is merged; `parrot_tools/querysource/*` is shared with any concurrent FEAT-558 follow-up (FEAT-593 Agent Studio config also lives there).
- **Recommended isolation**: `mixed`.
- **Rationale**: strands 1, 2 and 5 are self-contained modules with their own tests and can run in separate worktrees; strand 4 touches the shared server handler and should be one sequential task; strand 3 modifies a shipped toolkit and should be one focused task with its own tests. No external gate remains before `/sdd-task`.

---

## Open Questions

- [x] Flow type and base branch — *Owner: Jesus Lara*: `feature`, base `dev`.
- [x] Where the descriptor lives — *Owner: Jesus Lara*: surface-level `metadata.extensions.parrot_data_sources`; components bind by `path`; any surface, not only widgets.
- [x] Fetch path for the renderer — *Owner: Jesus Lara*: directly to QuerySource with the viewer's JWT (endpoint revised 2026-09-24: `POST /api/v3/queries/{slug}` / `/api/v1/{tenant}/queries/{slug}`, see below; v2 `services/queries` is legacy); no ai-parrot-server proxy. Python executor only for server-side lanes.
- [x] Transform DSL scope — *Owner: Jesus Lara*: ten ops incl. `join` and `union` (added when resolving the `MultiQuerySlugSource` question) (`inner|left`, equality keys, nulls never match, prefix on collision); no LLM-generated code; library input shapes (pie pairs) belong to the renderer.
- [x] `transform.ref` in v1 — *Owner: Jesus Lara*: yes, URL to a TypeScript module served by ai-parrot-server from a static, anonymously readable route, pinned by an `integrity` (SRI) hash; inline `ops` remains the rule.
- [x] Who may emit a descriptor — *Owner: Jesus Lara*: TOOL-origin builders only; LLM-origin envelopes fail `validate_envelope` (`DATA_SOURCES_NOT_ALLOWED_FOR_LLM`).
- [x] Refresh policy and persisted surfaces — *Owner: Jesus Lara*: `on_mount` default (`manual`/`interval` optional); `refreshable = recipe_name or data_sources`; `POST .../refresh` runs the Python executor with the owner's context.
- [x] `locked` conditions — *Owner: Jesus Lara*: UX hint only; security is QuerySource PBAC + slug design; documented as such.
- [x] Snapshot — *Owner: Jesus Lara*: optional in chat (the agent decides); mandatory once persisted — the save path produces it with the owner's context when missing; `GET` never executes.
- [x] Relative dates — *Owner: Jesus Lara*: QuerySource keyword vocabulary as condition values (`TODAY`, `FDOM`, ...), discovered through `describe`/`vocabulary`; no placeholder grammar.
- [x] TypeScript executor for `navigator-frontend-next` — *Owner: Jesus Lara*: ai-parrot ships no TypeScript for third parties; it publishes the descriptor/DSL JSON Schema and the golden fixtures, and each renderer implements its own executor against them. The bundled `ai-parrot-server/ui` implements its own executor too, as one renderer among others (not a reference).
- [x] FilterBar ↔ params contract — *Owner: Jesus Lara*: extend `FilterBar`; a filter with `metadata.extensions.parrot_param = {source, name}` re-fetches that source, without it the filter stays local (§7.4). No `ParamBar`.
- [x] `interval` refresh policy — *Owner: Jesus Lara*: 30 s minimum (model validator + renderer clamp), paused while `document.hidden`, immediate fetch on resume.
- [x] Snapshot row cap — *Owner: Jesus Lara*: 500 rows per source (`max_snapshot_rows`), `snapshot_truncated: true` when cut; the live fetch is not capped.
- [x] Share-token viewers denied by QuerySource — *Owner: Jesus Lara*: keep the last server-refreshed snapshot with a "data as of `snapshot_at`" notice and a server-side refresh button (owner context); no automatic server refresh.
- [x] ~~Multi-tenant slugs (QuerySource FEAT-176)~~ — *superseded 2026-09-24 (cross-check)*: FEAT-147 offers no session-derived tenant; `tenant` is descriptor content. See "FEAT-147 / FEAT-148 cross-check" below.
- [x] `ref` transform catalogue governance — *Owner: Jesus Lara*: static directory published per ai-parrot-server release with a signed `manifest.json` (`name@version` → integrity); the builder only accepts refs present in the manifest; retirement = `deprecated` flag in the manifest, files are never deleted.
- [x] `MultiQuerySlugSource` — *Owner: Jesus Lara*: N descriptors plus a tenth DSL operation `union` (concatenation by matching columns); no `multi_query_slug` kind.
- [x] HTML lane without snapshot — *Owner: Jesus Lara*: never happens for persisted surfaces: the save path (`POST /api/v1/ui/surfaces`, `publish_surface`) executes the descriptor once with the owner's context when the snapshot is missing and persists it; `GET` (JSON/HTML) never executes. In chat responses the snapshot stays optional.
- [x] ~~FEAT-567 sequencing~~ — *superseded 2026-09-24*: the toolkit shipped as FEAT-558 `QuerysourceToolkit` (done 2026-09-17) and QuerySource 5.0.0 is in production; no gate remains.

### Resolved on 2026-09-24 (re-verification rounds)

- [x] Params contract source — *Owner: Jesus Lara*: extend FEAT-558 `qs_describe_slug` — `PlaceholderInfo` gains `required` and `accepts_keywords` by calling `querysource.queries.describe.build_variables` in-process; no HTTP client to `GET …/describe`.
- [x] Relative-date grammar — *Owner: Jesus Lara*: QuerySource UDF keywords only (`TODAY`, `FDOM`, …); the dialect's deployment-defined `@variables` are rejected on the wire.
- [x] Where the agent tool lives — *Owner: Jesus Lara*: a new `build_linked_surface` tool on `QuerysourceToolkit` (`qs_build_linked_surface`); no separate `LinkedSurfaceToolkit`; a DatasetManager wrapper is a follow-up.
- [x] Snapshot / execution path — *Owner: Jesus Lara*: the Python executor over `QuerySlugSource.fetch` (no `max_rows` cap, 500-row snapshot cap) for chat, save and refresh; the builder **always** executes once, `snapshot` only decides whether rows are embedded.
- [x] Column types for axis validation — *Owner: Jesus Lara*: from the dtypes of the frame that mandatory execution returns; no `qs_columns` tool.
- [x] Fetch endpoint — *Owner: Jesus Lara*: `POST /api/v3/queries/{slug}` (single and MultiQuery slugs) and, when `source.tenant` is set, `POST /api/v1/{tenant}/queries/{slug}` (single-query only — see the cross-check); v2 `services/queries` is legacy, not targeted.
- [x] MultiQuery slugs — *Owner: Jesus Lara*: ordinary `query_slug` sources **when public**; *amended by the cross-check below*: tenant MultiQuery is rejected in v1 (no HTTP lane), and the descriptor carries `is_multiquery` for executor dispatch.
- [x] `conditions` shape — *Owner: Jesus Lara*: raw QuerySource payload **plus** the structured `request` block; the builder derives one from the other and refuses disagreement.
- [x] Sequencing — *Owner: Jesus Lara*: QuerySource 5.0.0 with FEAT-148 and tenant slug URLs is already in production; `/sdd-spec` proceeds now; the `querysource>=5.0.0` floor bump is a task of this feature.

### Resolved on 2026-09-24 (FEAT-147 / FEAT-148 cross-check)

Method: two independent fact sheets over `../querysource` (FEAT-147
per-tenant queries, FEAT-148 describe) plus a codex second opinion with a
neutral brief; every load-bearing claim was spot-checked in code before
adoption. Ten findings: nine CONFIRMed, three of them escalated (catalog,
tenant MultiQuery, relative offsets) and decided here *by the findings*, at
the author's request — they stand unless the author reopens them.

- [x] Tenant in the descriptor — `tenant: str | null` per source (QuerySource store schema; `null` = `public`). Rationale: FEAT-147 selects the store from the URL path or the `tenant=` keyword only, has no discovery endpoint and no membership check, and `resolve(None)` silently runs a same-named public slug. Independent of FEAT-535 `UISurfaceRecord.tenant`.
- [x] Catalog for tenant slugs (escalated) — tenant-aware `SlugCatalog` over `DefinitionRepository.get/.list` + `QueryIdentity`; the `programs` allowlist is unchanged because a tenant definition's runtime `program_slug` **is** its schema. Chosen over "public only in v1" because it is one module swap inside FEAT-558 and keeps the feature usable on the production multi-tenant deployment.
- [x] Server-lane tenant plumbing — `QuerySlugSource(tenant=)`, `QS`/`MultiQS` dispatch by `is_multiquery`, tenant taken from the descriptor (never `build_principal_context`'s defaulted `tenant_id`), `TenantError.error_code` → 404/503, trusted-service model written down (in-process QuerySource runs no PBAC).
- [x] Tenant MultiQuery (escalated) — rejected by the builder in v1 (`TENANT_MULTIQUERY_UNSUPPORTED`); a QuerySource bug is filed against FEAT-147's own route table; public MultiQuery unaffected. Chosen over "server-refresh-only tenant multi" because a source the renderer can never fetch breaks the linked-surface promise.
- [x] Relative offsets (escalated) — the "last week stays last week" claim is withdrawn; the vocabulary is closed (7 keywords, helpers non-invocable); `@variables` stay rejected in v1 as non-portable. Revisit only if a portable offset keyword lands in QuerySource.
- [x] `accepts_keywords` / `required` / `build_variables` — adopted exactly as implemented (`or raw_type is None`; static `required` with `IMPLICIT_DEFAULTS`; `DescribeVariable` objects); the in-process call reuses the parsing, not the endpoint's authorization/redaction — service-trust, like FEAT-558's `include_sql`.
- [x] Error semantics — renderer treats every 404 as "unavailable", never "denied" (QuerySource has no 403); server maps `TenantError.error_code` before falling back to 502.
- [x] `refresh` — boolean `true` only (`bool()` on the raw value); cache is scoped per store schema + definition revision, so bypass is tenant-safe once the tenant is right.
- [x] Floor — exactly `querysource>=5.0.0` (FEAT-147 + FEAT-148 both first in tag 5.0.0); the 5.1.7 tag's tree lacks `queries/describe.py` while `git tag --contains` lists it — verify that lineage before bumping past 5.0.0.
