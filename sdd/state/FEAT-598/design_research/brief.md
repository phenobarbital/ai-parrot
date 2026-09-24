<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
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

### Constraints and goals
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
  `TENANT_MULTIQUERY_UNSUPPORTED` **while the installed QuerySource is
  `< 5.1.0`** (`_qs.installed_version()` / `check_version_compatibility`,
  `dialect.py`): the FEAT-147 route fix is in progress (author,
  2026-09-24) and ships in QuerySource **5.1.0**, at which point the
  rejection lifts with no wire change. The descriptor carries `is_multiquery` so every
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

### Recommended option / probable scope
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

### Verified code anchors (paths only — open them yourself)
docs/outputs/a2ui-v1.md
packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py
packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py
packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/a2ui-types.ts
packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py
packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py
packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py
packages/ai-parrot/src/parrot/outputs/a2ui/baking.py
packages/ai-parrot/src/parrot/outputs/a2ui/builders.py
packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py
packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/filterbar.py
packages/ai-parrot/src/parrot/outputs/a2ui/models.py
packages/ai-parrot/src/parrot/outputs/a2ui/recipes/models.py
packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py
packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
sdd/tasks/.id_ledger.json

### Questions still open in the exploration document
none

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
