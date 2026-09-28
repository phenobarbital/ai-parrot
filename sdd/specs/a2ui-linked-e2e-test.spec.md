---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-tools, ai-parrot-server, ai-parrot-visualizations, admin-ui, docs]
tags: [a2ui, linked-surfaces, querysource, dashboard, e2e-example, echarts]
---

# Feature Specification: A2UI Linked Surfaces E2E example

**Feature ID**: FEAT-610
**Date**: 2026-09-28
**Author**: Jesus Lara
**Status**: approved
**Target version**: next release after ai-parrot 1.0.6

Source proposal: `sdd/proposals/a2ui-linked-e2e-test.proposal.md` (research state `sdd/state/FEAT-610/`).

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-598 (A2UI Linked Surfaces) has landed on `dev`, but nothing shows it working end to end against real data.
We need a self-contained example (no code outside the ai-parrot workspace, no navigator-frontend-next) that proves
three things:
- an ai-parrot agent can emit a **multi-widget linked dashboard** over one query-slug;
- a plain HTML5 client can render that dashboard;
- the client can **refresh every widget deterministically**, calling the QuerySource query-slug API with the viewer's
  bearer token and no LLM involved.

The data is `polestar_graduates_directory` (production, `public.queries`, data in schema `polestar`). The dashboard has:
- 4 KPI hero cards;
- 2 bar charts;
- 1 pie chart;
- 1 filterable, server-paged grid over all 17 572 rows.

Research (proposal §2) found these gaps:
- no helper composes a multi-widget linked surface (`qs_build_linked_surface` builds one component per call);
- the toolkit's filter validator **rejects the JSONB `@>` operator** that two KPIs need;
- no renderer refreshes per widget (the TS lane only exposes `refreshAll`);
- the Python ECharts mapper emits unnamed pie slices;
- the linked-surfaces wire doc §3 disagrees with the code;
- core `ai-parrot[db]` still pins `querysource>=4.1.11`.

### Goals
- G1 — An agent (`Agent` + `QuerysourceToolkit`) emits one TOOL-origin linked `createSurface` holding 4 KPICards, 2 bar
  Charts, 1 pie Chart and 1 DataTable, with a single call to a new `qs_build_linked_dashboard` tool.
- G2 — `examples/a2ui/server.py` is an aiohttp app. It mounts QuerySource, `AuthHandler` (BasicAuth, no PBAC policy),
  optionally BotManager, serves the static renderer, and serves the agent-built surface at its own route.
- G3 — `examples/a2ui/static/` is an HTML5 renderer (ECharts + grid.js, vanilla JS) that logs in, stores the JWT in
  `localStorage`, renders the surface, and offers a **per-widget refresh** plus a **"Refresh all"**. Both call the
  QuerySource API deterministically.
- G4 — The grid pages on the server over all 17 572 rows, with a stable `ordering`. Its column filters (country,
  licensee, is_requalified) become QuerySource `filter` entries.
- G5 — `examples/a2ui/client.py` opens the page (`--open`) and runs a headless smoke check (`--check`): log in, fetch
  the surface, re-fetch every source, print widget values.
- G6 — Core fixes that the demo depends on:
  - the toolkit accepts JSONB operators;
  - the querysource floor is `>=5.1.2`;
  - pie slices get names;
  - `LinkedLane` exposes `refreshSource(key)` and `A2UISurface.svelte` wires both refresh affordances;
  - the wire doc is corrected.
- G7 — The course pie reads a second, seeded slug `polestar_graduates_by_course` (interim; see §7 follow-ups QS-2).

### Non-Goals (explicitly out of scope)
- The server-lane `POST /api/v1/ui/surfaces/{id}/refresh` and the persisted `PgUISurfaceStore`. The example serves its
  own surface route.
- Changes to the FEAT-598 descriptor schema (`LinkedDataSource`) or new catalog components (a Grid container, a
  refresh prop). Refresh is a renderer affordance, not wire data.
- A demo auth backend, NoAuth, or any PBAC policy (the user decided: basic authentication only).
- QuerySource features QS-1 (JSONB array-length filter operator) and QS-2 (GROUP BY over JSONB array elements). These
  are follow-ups in the `querysource` repo (§7).
- The Python executor's `transform.ref` skip and the `ensure_snapshot` owner re-check (F008). Log them in the ledger if
  they still matter.
- Running on navigator-frontend-next, or adding JS/Python libraries that ai-parrot does not already ship or reference.

---

## 2. Architectural Design

### Overview

**Agent side.** A new toolkit method `QuerysourceToolkit.build_linked_dashboard` (tool `qs_build_linked_dashboard`)
takes a list of widget specs. Each spec has:
- `key` — the data-model root and source key;
- `slug`, `request` (qs grammar), `tenant`;
- `component` — Chart, DataTable or KPICard, unbound.

The method builds one `LinkedDataSource` per widget, reusing the same derivation as `build_linked_surface` (describe,
validate, `derive_conditions`, `_linked_params`). It runs every source once through `execute_sources`, binds each
component to its own key with `_bind_component`, and arranges them in a layout:
- root `Column`;
- a KPI `Row`;
- a chart `Row`;
- the DataTable.

It calls `builders.build_linked_surface` once, so the whole dashboard is **one TOOL-origin envelope**. Descriptors are
legal only on TOOL output (`DATA_SOURCES_NOT_ALLOWED_FOR_LLM`), so the agent must call this tool; it cannot author
the JSON itself.

**Dialect.** `dialect.py` gains `JSONB_OPERATORS = ("@>", "<@", "@>|", "->", "->>")`, mirroring
`querysource/parsers/pgsql.pyx:29`. `validate_filter` accepts them in the `{op: value}` form, with a dict/list operand
allowed. `DialectReference` advertises them, and `DIALECT_VERIFIED_AGAINST` moves to `"5.1.2"`. Without this change,
the Pilates KPIs fail validation today (`InvalidConditionsError: unknown dict operator '@>'`, verified).

**Example server.** `examples/a2ui/server.py` works as follows:
- **Mount order** (the `app.py` precedent): `QuerySource(lazy=False).setup(app)`, then optionally
  `BotManager(enable_database_bots=False, enable_registry_bots=False).setup(app)` plus `add_agent`, then
  `AuthHandler().setup(app)` last, with `auth_exclude_list` extended by `/`.
- **Routes:**
  - `GET /` → `static/index.html`;
  - `/static/` → assets;
  - `GET /api/a2ui/dashboard` → the envelope. The first call runs the dashboard agent; the result is cached in
    `app`, and `?rebuild=1` re-runs it. The server takes the envelope from `AIMessage.tool_calls[*].result["a2ui_envelope"]`
    for the tool call named `qs_build_linked_dashboard`.
- **Environment:** the server fails fast when `querysource < 5.1.2`, runs with `QS_PBAC_ENABLED=false` (documented),
  and always needs `ENV=prod` for this data.

**Example client.** The static page:
1. POSTs `/api/v1/login` with `X-Auth-Method: BasicAuth` (the `admin_login_page` pattern) and stores the token under
   `ai_parrot_token` in `localStorage`.
2. GETs the surface with `Authorization: Bearer <token>` and walks the v1.0 component tree.
3. Renders each component natively:
   - KPICard → hero card;
   - Chart bar/pie → an ECharts option built in JS (`{name, value}` slices for pie; a NULL category is labelled
     "Unassigned");
   - DataTable → grid.js in `server` mode.
4. Refreshes with `linked.js`, a vanilla-JS port of the FEAT-598 TS lane (`queryUrl`, `fetchSource`, frame selection,
   `querylimit` cap 5000, 404 → "unavailable"):
   - `refreshSource(key)` repaints only the widgets bound to that key;
   - `refreshAll()` re-fetches every source.
5. Pages the grid by overriding the grid source's conditions with `querylimit`, `_offset`, `ordering` and the
   column-filter `filter`; a parallel `count(*)` call on the same filter gives the total.

**Rendering and data sources.**
- The snapshot (≤500 rows) paints first; live data replaces it.
- Every widget's source is its own key, even when two widgets share a slug, so a per-widget refresh is exactly one
  request.

**Admin UI parity.** `LinkedLane.refreshSource(key)` (new, beside `refreshAll`). `A2UISurface.svelte` adds a
"Refresh all" control and a per-widget refresh control for bound components, forwarding through `laneProxy`.

**Verified query map** (live, querysource 5.1.2, `ENV=prod`, authenticated; F040/F042):

| Widget | key | slug | request | Expected |
|---|---|---|---|---|
| KPI total | `kpi_total` | `polestar_graduates_directory` | `fields: ["count(*) as total"]` | 17572 |
| KPI Pilates Studio | `kpi_studio` | same | `fields: ["count(*) as total"]`, `filter: {"graduation_details": {"@>": [{"course": "Pilates Studio"}]}}` | 9191 (people) |
| KPI Pilates Mat | `kpi_mat` | same | same, with `"Pilates Mat"` | 6245 (people) |
| KPI multi-graduates | `kpi_multi` | same | `fields: ["count(*) FILTER (WHERE jsonb_array_length(graduation_details) > 1) AS multi_graduates"]` | 2884 |
| Bar by country | `by_country` | same | `fields: ["country", "count(*) as graduates"]`, `grouping: ["country"]` | 95 groups (94 + NULL) |
| Bar by licensee | `by_licensee` | same | `fields: ["licensee", "count(*) as graduates"]`, `grouping: ["licensee"]` | 23 groups (22 + NULL = 7103) |
| Pie by course | `by_course` | `polestar_graduates_by_course` (seeded) | `fields: ["course", "count(*) as graduates"]`, `grouping: ["course"]` | Studio 9204 · Mat 6247 · Rehab 3300 · Reformer 2048 (diplomas) |
| Grid | `graduates` | `polestar_graduates_directory` | `fields: [student_uid, full_name, country, licensee, is_requalified, last_diploma_date]`, `ordering: ["student_uid"]`, `limit: 500` | 17572 rows, paged |

The KPIs count **people**; the pie counts **diplomas**. The widget labels must say which is which.

### Component Diagram
```
Agent(QuerysourceToolkit) ──qs_build_linked_dashboard──→ execute_sources ──→ QuerySlugSource (in-process QS)
        │                                     └──→ builders.build_linked_surface ──→ CreateSurface (TOOL origin)
        ▼
examples/a2ui/server.py ── GET /api/a2ui/dashboard ──→ envelope JSON
        │  (QuerySource.setup · AuthHandler.setup · [BotManager])
        ▼
static/index.html ─ renderer.js ─┬─ KPICard → hero card
   (JWT in localStorage)         ├─ Chart → ECharts
                                 ├─ DataTable → grid.js (server mode)
                                 └─ linked.js ── POST /api/v3/queries/{slug} (or /api/v1/queries/{tenant}/{slug})
                                                 per-widget refreshSource(key) · refreshAll()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `QuerysourceToolkit` | extends (new tool method) | `build_linked_dashboard` beside `build_linked_surface` (`toolkit.py:339`) |
| `builders.build_linked_surface` | uses | composes the multi-source envelope (`builders.py:514`) |
| `linked.executor.execute_sources` | uses | one pass over all widget sources (`executor.py:180`) |
| `dialect.validate_filter` / `DialectReference` | modifies | accepts and advertises the JSONB operators (`dialect.py:135`, `:95`) |
| `EChartsRenderer._build_option` | modifies | pie/donut `{name, value}` slices (`echarts.py:279`) |
| `LinkedLane` / `A2UISurface.svelte` | modifies | `refreshSource(key)` + refresh affordances (`index.ts:54-61`, `A2UISurface.svelte:101-106`) |
| `QuerySource.setup`, `AuthHandler.setup`, `BotManager` | uses | example server wiring (`app.py:109-113`, `form_server.py:59-66`) |
| `Agent` | uses | dashboard agent (`parrot/bots/__init__.py:2`) |

### Data Models
```python
# packages/ai-parrot-tools/src/parrot_tools/querysource/models.py  (new model, beside SlugDetail etc.)
class DashboardWidget(BaseModel):
    """One widget of a linked dashboard: its own source key, slug, request, and unbound component."""
    key: str                                  # data-model root + source key (JSON-pointer-safe)
    slug: str
    component: dict[str, Any]                 # Chart | DataTable | KPICard, without its binding
    request: dict[str, Any] | None = None     # qs grammar: placeholders/filter/fields/ordering/grouping/limit/offset
    tenant: str | None = None
    section: Literal["kpis", "charts", "table"] | None = None   # layout row; inferred from component when None
    refresh: dict[str, Any] | None = None     # RefreshPolicy payload
```

### New Public Interfaces
```python
class QuerysourceToolkit(AbstractToolkit):
    async def build_linked_dashboard(
        self,
        widgets: list[dict[str, Any]],
        surface_id: str | None = None,
        title: str | None = None,
        snapshot: bool = True,
    ) -> dict[str, Any]:
        """Emit ONE linked A2UI dashboard surface (tool `qs_build_linked_dashboard`)."""
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: JSONB dialect | yes | `JSONB_OPERATORS` tuple, `validate_filter` branch, `DialectReference.operators_jsonb`, version string | — |
| M2: dashboard tool | no | — | layout inference and key-collision rules need judgement against the builder |
| M3: pins + floor test | yes | exact strings in §6 Edit Sites | — |
| M4: ECharts pie names | yes | funnel/treemap pattern at `echarts.py:537-543` | — |
| M5: TS lane refresh | yes | `refreshSource(key): Promise<void>` mirroring `setParam`'s delete + `runSource` | — |
| M6: wire doc + toolkit doc | yes | text in §2 / §7 | — |
| M7: example server + agent | no | — | agent prompt and envelope extraction need judgement |
| M8: static renderer | no | — | vanilla port of the TS lane plus grid.js server mode |
| M9: client + seed + README + gitignore | yes | CLI flags and seed SQL fixed in §3 M9 | — |

### Module 1: JSONB operators in the toolkit dialect
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py`, `models.py`
- **Responsibility**: accept and advertise the querysource ≥5.1 JSONB operators, and bump the verified dialect version.
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  # dialect.py (modifies dialect.py:20, :49, :95, :148)
  DIALECT_VERIFIED_AGAINST: str = "5.1.2"                              # verified: dialect.py:20 (was "4.5.11")
  JSONB_OPERATORS: tuple[str, ...] = ("@>", "<@", "@>|", "->", "->>")  # mirrors querysource/parsers/pgsql.pyx:29
  def validate_filter(filter: dict[str, FilterValue], *, strict: bool = True) -> list[str]:  # verified: dialect.py:135
      """... `{op: v}` accepts DICT_OPERATORS (scalar v) or JSONB_OPERATORS (dict/list/scalar/JSON-text v)."""
  # models.py (modifies DialectReference, verified: models.py:127)
  class DialectReference(BaseModel):
      operators_jsonb: list[str] = Field(default_factory=list)   # new; filled with list(JSONB_OPERATORS)
  ```

### Module 2: `qs_build_linked_dashboard` tool
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py`, `models.py`
- **Responsibility**: build one TOOL-origin linked surface from N widgets. Rules:
  - one `LinkedDataSource` per widget key (keys must be unique and JSON-pointer-safe, else `InvalidConditionsError`);
  - one `execute_sources` pass; any failed source raises `QuerysourceToolkitError` naming the key and the error code;
  - layout: root `Column` → `Row` of KPICards → `Row` of Charts → DataTables; empty rows are omitted; component ids
    are the widget keys; every widget must be reachable from `root` through `children` (S1 — the renderers only walk
    from `root`, so an unreachable widget silently disappears);
  - `component` types are limited to Chart, DataTable and KPICard; a KPICard widget must name its aggregate column
    explicitly (`component.value` = the column name), never rely on an implicit first column (S3);
  - returns `{"a2ui_envelope": ..., "artifacts": [{"type": "a2ui_linked_surface", "surface_id", "sources": [...keys]}]}`.
- **Depends on**: M1 (the `@>` KPIs must validate)
- **Interface Skeleton**:
  ```python
  # toolkit.py (new method inserted before toolkit.py:415 `_linked_params`)
  async def build_linked_dashboard(
      self,
      widgets: list[dict[str, Any]],
      surface_id: str | None = None,
      title: str | None = None,
      snapshot: bool = True,
  ) -> dict[str, Any]:
      """Emit ONE linked A2UI dashboard: each widget {key, slug, component, request?, tenant?, section?, refresh?}
      gets its own source (so each refreshes independently); KPIs, charts and tables are laid out in rows.
      Components are Chart, DataTable or KPICard without bindings. Raises InvalidConditionsError on bad/duplicate
      keys or grammar; QuerysourceToolkitError when a source fails to execute."""
  def _build_linked_source(self, widget: DashboardWidget, detail: SlugDetail) -> LinkedDataSource:
      """Shared by build_linked_surface and build_linked_dashboard (extracted from toolkit.py:365-386)."""
  @staticmethod
  def _dashboard_layout(components: list[dict[str, Any]], widgets: list[DashboardWidget], title: str | None) -> list[dict[str, Any]]:
      """Return [root Column, Row(kpis)?, Row(charts)?, *components] with ids = widget keys."""
  ```

### Module 3: querysource floor
- **Path**: `packages/ai-parrot/pyproject.toml`, `packages/ai-parrot-tools/pyproject.toml`, `uv.lock`,
  `packages/ai-parrot-tools/tests/querysource/test_querysource_floor.py`
- **Responsibility**: `querysource>=5.1.2` in `ai-parrot[db]`, `ai-parrot[integrations]` and `ai-parrot-tools[db]`; the
  floor test follows. `uv.lock` is regenerated with `uv lock` (lock only — never `uv sync` in the worktree) so it
  resolves querysource ≥5.1.2; today it pins 5.1.1 (`uv.lock:13047`) (S6). There is no runtime gate in the toolkit (FEAT-598 AC12 is kept).
- **Depends on**: —
- **Interface Skeleton**: none (packaging only).

### Module 4: ECharts pie slice names
- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py`
- **Responsibility**: for `pie`/`donut`, series `data` becomes `[{"name": row[x], "value": row[y]}]` (the funnel/treemap
  pattern), with `None` names rendered as `"Unassigned"`. Other chart types are unchanged.
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  # echarts.py (modifies EChartsRenderer._build_option, verified: echarts.py:192, series loop :276-283)
  def _build_option(self, props: dict[str, Any]) -> dict[str, Any]:
      """... pie/donut series carry {name, value} slices keyed by props['x'] (FEAT-610)."""
  ```

### Module 5: per-source refresh in the admin UI lane
- **Path**: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.ts`,
  `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UISurface.svelte`
- **Responsibility**:
  - `LinkedLane.refreshSource(key)`: a no-op for unknown or failed keys; otherwise delete the frame and run
    `runSource(key, true)`, then re-run the sources whose `transform` references `key`, in the existing dependency
    order (S5). The key is resolved from the widget's `/key/...` binding; the browser never sends a slug or conditions
    of its own (S4). Concurrent calls for the same key share one in-flight request.
  - `refreshAll()` keeps its current dependency-ordered schedule; it is not parallelized (S5).
  - `A2UISurface.svelte`: add `refreshSource` to `laneProxy`; render a "Refresh all" control for linked surfaces and a
    per-component refresh control for Chart/DataTable/KPICard bound to a source (Svelte 5 runes only).
- **Depends on**: —
- **Interface Skeleton**:
  ```ts
  // index.ts (modifies interface LinkedLane, verified: index.ts:54-61; return object :203-235)
  export interface LinkedLane {
    /** Manual refresh of ONE source (per-widget refresh button). Unknown/failed keys are a no-op. */
    refreshSource(key: string): Promise<void>;
  }
  ```

### Module 6: docs
- **Path**: `docs/outputs/a2ui-linked-surfaces.md`, `docs/tools/querysource-toolkit.md`
- **Responsibility**:
  - §3 of the wire doc lists all four fetch routes (`/api/v3/queries/{slug}`; `/api/v1/{tenant}/queries/{slug}`;
    `/api/v1/queries/{schema}/{slug}` alias, querysource ≥5.1.2; `/api/v2/services/queries/{slug}`), gives the
    `querylimit` cap as 5000, and says `refresh` is sent only when true.
  - It documents per-source refresh.
  - The toolkit doc covers `qs_build_linked_dashboard` and the JSONB operators.
- **Depends on**: M1, M2, M5

### Module 7: example server and dashboard agent
- **Path**: `examples/a2ui/server.py`, `examples/a2ui/dashboard.py`
- **Responsibility**:
  - `dashboard.py` holds the verified `WIDGETS` list (the §2 query map), `build_dashboard_agent()` (an `Agent` with
    `QuerysourceToolkit(programs=["polestar"])` and a prompt that passes `WIDGETS` to one `qs_build_linked_dashboard`
    call), and `extract_envelope(response)`.
  - `server.py` wires the app as in §2 Overview, with a version fail-fast and a CLI (`--host`, `--port`,
    `--with-agent-api`, `--llm` defaulting to `anthropic:claude-sonnet-5`).
- **Depends on**: M2 (the tool), M1
- **Interface Skeleton**:
  ```python
  # examples/a2ui/dashboard.py (new)
  WIDGETS: list[dict[str, Any]]   # the §2 verified query map, exactly
  def build_dashboard_agent(llm: str | None = None) -> Agent:
      """Agent named 'polestar-dashboard' with QuerysourceToolkit(programs=['polestar'])."""
  def extract_envelope(response: AIMessage) -> dict[str, Any]:
      """Return tool_calls[name=='qs_build_linked_dashboard'].result['a2ui_envelope']; raise RuntimeError if absent
      or without parrot_data_sources."""
  # examples/a2ui/server.py (new)
  def create_app(*, with_agent_api: bool = False, llm: str | None = None) -> web.Application: ...
  async def dashboard_handler(request: web.Request) -> web.Response:
      """GET /api/a2ui/dashboard[?rebuild=1] → cached envelope JSON."""
  def require_querysource(min_version: str = "5.1.2") -> None:
      """Exit with a clear message when querysource is older than min_version."""
  async def check_slugs(app: web.Application) -> None:
      """on_startup, read-only: verify both slugs exist; if `polestar_graduates_by_course` is missing, log the
      `seed_by_course.py --yes` hint and render that widget as 'unavailable' (never seed at startup — S9)."""
  ```

### Module 8: static HTML5 renderer
- **Path**: `examples/a2ui/static/index.html`, `static/renderer.js`, `static/linked.js`, `static/styles.css`
- **Responsibility**:
  - login form, JWT in `localStorage` (`ai_parrot_token`), logout;
  - surface fetch and v1.0 tree walk (Column/Row/Card layout, with a visible notice for unknown components — degrade,
    never throw);
  - KPICard hero cards, ECharts bar/pie, and a grid.js DataTable in server mode (paging via `querylimit`/`_offset`,
    stable `ordering`, column filters → `filter`, total via `count(*)`). Paging is example-specific: `fetchPage` lives
    only in `static/linked.js` and is NOT a wire-contract extension. It reuses the grid source descriptor (slug,
    tenant, locked conditions) and overrides only `querylimit`/`_offset`/`ordering`/the column `filter`. The admin UI
    DataTable (M5) keeps the bounded frame (≤5000 rows) (S2);
  - a per-widget refresh button, "Refresh all", and per-widget loading/error/"unavailable" states.

  Libraries:
  - ECharts is the vendored `echarts.min.js`, copied into `static/vendor/` at build time or served from the installed
    `parrot.outputs.formats.assets` package path by `server.py`;
  - grid.js is `gridjs@6.2.0` from unpkg (the version the repo already references), pinned with real `sha384` SRI
    hashes computed from the exact files (`dist/gridjs.umd.js` and the theme `dist/theme/mermaid.min.css`); the placeholders in
    `interactive/catalog/libraries/gridjs.md` must not be copied (S7). grid.js is MIT-licensed. Not vendored: the user's
    constraint is no library ai-parrot does not already reference.
- **Depends on**: M7 (surface route); mirrors M5 semantics.
- **Interface Skeleton**:
  ```js
  // static/linked.js (new) — vanilla port of ui/.../a2ui/linked/{fetch,index}.ts
  export const DEFAULT_MAX_FETCH_ROWS = 5000;
  export function queryUrl(baseUrl, slug, tenant) {}            // v3 without tenant, /api/v1/queries/{tenant}/{slug} with
  export async function fetchSource(src, conditions, { baseUrl, token, maxFetchRows }) {}  // → rows; 404 → SourceUnavailable
  export function createLane(sources, { baseUrl, token, onUpdate }) {}  // → { start, refreshSource(key), refreshAll(), fetchPage(key, {offset, limit, filter}) }
  ```

### Module 9: client, slug seed, README, gitignore
- **Path**: `examples/a2ui/client.py`, `examples/a2ui/seed_by_course.py`, `examples/a2ui/README.md`, `.gitignore`
- **Responsibility**:
  - `client.py --open` opens the browser.
  - `client.py --check --user U` (password from `A2UI_DEMO_PASSWORD`) logs in, fetches the surface, re-fetches every
    source through the same route rule, and prints a value table. It exits non-zero on any failure. It uses aiohttp only.
  - `seed_by_course.py` upserts `polestar_graduates_by_course` idempotently with a SQL upsert into
    `public.queries` that copies the base slug's row columns (not the QS management API). Use
    `INSERT … ON CONFLICT (query_slug)` only if the table has a unique key on `query_slug` (unverified — check before
    use); otherwise UPDATE, then INSERT when no row was updated, in one transaction. It asks for explicit confirmation
    (`--yes`) because it writes to **production** `public.queries`. The SQL:
    ```sql
    SELECT {fields} FROM (SELECT d.student_uid, e->>'course' AS course, e->>'category' AS category
      FROM polestar.vw_graduates_directory d
      CROSS JOIN LATERAL jsonb_array_elements(d.graduation_details) e
      WHERE e->>'course' IS NOT NULL) t {where_cond}
    ```
  - The README covers `ENV=prod`, `QS_PBAC_ENABLED=false`, querysource ≥5.1.2, and the run order.
  - `.gitignore` whitelists `examples/a2ui/**` (`*.py`, `*.html`, `*.js`, `*.css`), with narrowly scoped `!` rules;
    validated by `git check-ignore -v examples/a2ui/server.py examples/a2ui/static/index.html` returning nothing (S10).
- **Depends on**: M7, M8

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_validate_filter_accepts_jsonb_operators` | M1 | `@>` with a list-of-dict, `<@`, `@>|`, `->>` accepted; an unknown operator is still rejected |
| `test_dialect_reference_lists_jsonb_operators` | M1 | `operators_jsonb` populated; `verified_against == "5.1.2"` (update `test_toolkit_core.py:79`, `test_models.py:40`) |
| `test_build_linked_dashboard_reachability` | M2 | every widget id is reachable from `root` via `children`; every `/key/…` binding has a source (S1, S8) |
| `test_build_linked_dashboard_one_envelope` | M2 | 8 widgets → one CreateSurface; 8 sources keyed by widget key; root Column + KPI Row + chart Row + table |
| `test_build_linked_dashboard_kpi_bindings` | M2 | KPICard `value` → `{"path": "/<key>/rows/0/<col>"}` |
| `test_build_linked_dashboard_duplicate_key` | M2 | duplicate or unsafe key → `InvalidConditionsError` |
| `test_build_linked_dashboard_source_failure` | M2 | a failed source → `QuerysourceToolkitError` naming the key |
| `test_tool_names_and_write_gate` (update) | M2 | pinned tool list gains `qs_build_linked_dashboard` (`test_toolkit_core.py:18,28`) |
| `test_querysource_floor_is_5_1_2` (update) | M3 | `querysource>=5.1.2` in ai-parrot-tools `db` |
| `test_pie_slices_have_names` | M4 | pie/donut series data is `{name, value}`; NULL name → "Unassigned"; bar unchanged |
| `index.test.ts: refreshSource` | M5 | re-fetches only that key; unknown key no-op; `refreshAll` unchanged (vitest) |
| `A2UISurface.linked.test.ts` (extend) | M5 | the per-widget control calls `refreshSource(key)`; "Refresh all" calls `refreshAll` |
| `test_extract_envelope` | M7 | picks the `qs_build_linked_dashboard` ToolCall result; raises when absent |

### Integration Tests
| Test | Description |
|---|---|
| `test_dashboard_example_server_routes` | `create_app()` with QuerySource/AuthHandler/agent patched: `/` serves HTML, `/api/a2ui/dashboard` returns an envelope with `parrot_data_sources`, and a request without a token is rejected |
| `test_linked_dashboard_live` *(opt-in: `PARROT_TEST_QS_LIVE=1`, `ENV=prod`)* | real `build_linked_dashboard` on the 8 widgets: KPI values equal §2 Expected; group counts 95/23; pie slices |

### Test Data / Fixtures
```python
@pytest.fixture
def dashboard_widgets():  # mirrors examples/a2ui/dashboard.py WIDGETS (import it, do not copy)
    ...
```
Reuse `fake_core_qs` / `patched_qs` from `packages/ai-parrot-tools/tests/querysource/` (conftest and
`test_build_linked_surface_tool.py:16-40`).

---

## 5. Acceptance Criteria

- [ ] AC1 — `qs_build_linked_dashboard` returns ONE TOOL-origin `createSurface` holding 4 KPICards, 2 bar Charts, 1 pie
  Chart and 1 DataTable, each bound to its own source key, and validated by `validate_envelope(..., origin=TOOL)`.
- [ ] AC2 — `validate_filter` accepts `{"graduation_details": {"@>": [{"course": "Pilates Studio"}]}}`, and the Pilates
  KPIs build through the tool.
- [ ] AC3 — `querysource>=5.1.2` in `ai-parrot[db]`, `ai-parrot[integrations]` and `ai-parrot-tools[db]`; the floor
  test is updated; `DIALECT_VERIFIED_AGAINST == "5.1.2"`.
- [ ] AC4 — The ECharts pie/donut series carry `{name, value}` slices; `None` → "Unassigned".
- [ ] AC5 — `LinkedLane.refreshSource(key)` exists and re-fetches only that key; `A2UISurface.svelte` shows a
  per-widget refresh and a "Refresh all"; vitest passes.
- [ ] AC6 — `examples/a2ui/server.py` starts with `ENV=prod QS_PBAC_ENABLED=false`, mounts QuerySource + AuthHandler
  (BasicAuth, no PBAC policy), serves `/` and `/api/a2ui/dashboard`, and exits with a clear message on
  querysource < 5.1.2.
- [ ] AC7 — The browser client logs in, keeps the JWT in `localStorage`, renders all 8 widgets, and shows these values
  (prod, 2026-09-28): 17572 / 9191 / 6245 / 2884, 95 country groups, 23 licensee groups, and pie slices 9204 / 6247 /
  3300 / 2048. NULL buckets are labelled "Unassigned".
- [ ] AC8 — Each widget's refresh issues exactly one QuerySource request for its own source and repaints only that
  widget. "Refresh all" re-fetches every source. Neither involves the LLM.
- [ ] AC9 — The grid pages on the server over 17 572 rows with a stable `ordering` (column filters only, no free-text
  search); its column filters change the rows
  and the total.
- [ ] AC10 — `client.py --check` exits 0 against a running server and prints the AC7 values.
- [ ] AC11 — `seed_by_course.py` is idempotent and refuses to write without `--yes`.
- [ ] AC12 — `docs/outputs/a2ui-linked-surfaces.md` §3 lists the four routes, the 5000 cap and the `refresh` semantics;
  `docs/tools/querysource-toolkit.md` documents the new tool and the JSONB operators.
- [ ] AC13 — The example files are tracked (the `.gitignore` whitelist); no token, password or DSN is committed.
- [ ] AC14 — The unit tests listed in §4 pass (`pytest packages/ai-parrot-tools/tests/querysource
  packages/ai-parrot-visualizations/tests -k "jsonb or dashboard or floor or pie"`, plus `pnpm vitest` for M5).
- [ ] AC15 — No new runtime dependency beyond what ai-parrot already ships or references (ECharts vendored,
  gridjs@6.2.0 via unpkg with SRI).

---

## 6. Codebase Contract

> Verified against `91c9e3e31` (dev, 2026-09-28).

### Verified Imports
```python
from parrot.outputs.a2ui.builders import build_linked_surface          # builders.py:514
from parrot.outputs.a2ui.linked.executor import execute_sources        # executor.py:180
from parrot.outputs.a2ui.linked.conditions import derive_conditions    # conditions.py:17
from parrot.outputs.a2ui.linked.models import LinkedDataSource, RefreshPolicy, SourceRequest, TransformSpec, ParamSpec  # models.py:192,43,30,178,19
from parrot.outputs.a2ui import LinkedDataSource                        # a2ui/__init__.py:45
from parrot.outputs.a2ui.linked import has_data_sources                # linked/__init__.py:60
from parrot_tools.querysource.toolkit import QuerysourceToolkit        # toolkit.py:64
from parrot_tools.querysource.dialect import validate_filter, DICT_OPERATORS, DIALECT_VERIFIED_AGAINST  # dialect.py:135,49,20
from parrot_tools.querysource.errors import InvalidConditionsError     # used by tests (test_build_linked_surface_tool.py:12)
from parrot.bots import Agent                                          # bots/__init__.py:2
from parrot.models.basic import ToolCall                               # basic.py:23 (fields: id, name, arguments, result, error)
from parrot.models.responses import AIMessage                          # responses.py:93 (tool_calls :157, a2ui_envelope :212)
from parrot.manager import BotManager                                  # app.py:9
from parrot.autonomous.admin import admin_login_page                   # admin.py:394 (form_server.py:28)
from navigator_auth import AuthHandler                                 # app.py:6
from querysource.services import QuerySource                           # app.py:7
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/builders.py
def build_linked_surface(components: Sequence[dict[str, Any]], sources: Mapping[str, "LinkedDataSource"],
    frames: Mapping[str, "pd.DataFrame"], *, surface_id: str, snapshot: bool = True, max_snapshot_rows: int = 500,
    catalog_id: str = DEFAULT_CATALOG_ID) -> CreateSurface:                                   # line 514
def _rows_key(binding, sources) -> tuple[str, str | None] | None:                             # line 460 (KPI: /<key>/rows/0/<col>)

# packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py
class SourceRequest(BaseModel):  # line 30 — placeholders, filter, fields, ordering, grouping, limit, offset
class LinkedDataSource(BaseModel):  # line 192 — kind, slug, tenant, is_multiquery, multi_output, conditions, request,
    # params, locked, transform, target (JSON pointer), snapshot_at, snapshot_truncated, refresh

# packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py
async def execute_sources(sources, *, param_overrides=None, pctx=None, guard=None, max_snapshot_rows=None,
    max_fetch_rows: int = 5000) -> ExecutionOutcome:                                           # line 180

# packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py
class QuerysourceToolkit(AbstractToolkit):                                                     # line 64
    tool_prefix = "qs"                                                                         # line 72
    def __init__(self, programs=None, allow_write=False, allow_raw_sql=False, allow_external_sources=True,
        include_sql=True, max_rows=200, forced_conditions=None, dsn=None, multiquery_timeout=600.0, **kwargs)  # line 77
    async def describe_slug(self, slug: str, dry_run: bool = False, tenant: str | None = None) -> SlugDetail:  # line 210
    async def build_linked_surface(self, slug, component, request=None, tenant=None, snapshot=True, surface_id=None,
        target_key=None, refresh=None, transform=None) -> dict[str, Any]:                      # line 339 (source build :365-386)
    def _linked_params(self, detail: SlugDetail, forced: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:  # line 415
    @staticmethod
    def _default_target_key(slug: str) -> str:                                                 # line 436
    @staticmethod
    def _bind_component(component: dict[str, Any], key: str) -> dict[str, Any]:                # line 442

# packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py
DIALECT_VERIFIED_AGAINST: str = "4.5.11"                                                       # line 20
DICT_OPERATORS: tuple[str, ...] = (">=", "<=", "<>", "!=", "<", ">")                           # line 49
def validate_filter(filter: dict[str, FilterValue], *, strict: bool = True) -> list[str]:     # line 135
def check_version_compatibility(installed: str) -> str | None:                                 # line 196

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py
class EChartsRenderer(AbstractA2UIRenderer):                                                   # line 107
    def _build_option(self, props: dict[str, Any]) -> dict[str, Any]:                          # line 192

# packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.ts
export interface LinkedLane { start(); stop(); setParam(source, name, value): Promise<void>; refreshAll(): Promise<void>; }  // lines 54-61
export function createLinkedLane(sources: LinkedSources, opts: LinkedLaneOptions): LinkedLane  // line 140
async function runSource(key: string, forceRefresh: boolean, resolving?: Set<string>): Promise<void>  // line 161 (internal)
// fetch.ts: DEFAULT_MAX_FETCH_ROWS = 5000 (line 13); api/querysource.ts queryUrl (lines 21-24)

# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:
    def __init__(self, enable_database_bots=..., enable_crews=..., enable_registry_bots=..., enable_swagger_api=...)  # line 193
    def add_agent(self, agent: AbstractBot) -> None:                                           # line 1179
    def setup(self, app: web.Application, *, agent_mount_config=None, ...) -> web.Application:  # line 2239
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `build_linked_dashboard` | `describe_slug`, `_linked_params`, `_bind_component` | method calls | `toolkit.py:210,415,442` |
| `build_linked_dashboard` | `execute_sources` | one call, all keys | `executor.py:180` |
| `build_linked_dashboard` | `builders.build_linked_surface` | one call | `builders.py:514` |
| `extract_envelope` | `AIMessage.tool_calls[*].result` | attribute access | `responses.py:157`, `basic.py:23-30` |
| `server.py` | `QuerySource(lazy=False).setup(app)` | app setup | `app.py:109-110` |
| `server.py` | `AuthHandler().setup(app)`; `app["auth_exclude_list"]` | app setup | `form_server.py:59-66` |
| `static/linked.js` | QuerySource routes (v3 / v1 tenant / v1 schema alias) | HTTP POST + Bearer | live, F042 |
| `refreshSource` | `runSource(key, true)` | internal call | `index.ts:161` |

### Does NOT Exist (Anti-Hallucination)
- ~~`QuerysourceToolkit.build_linked_dashboard`~~ / ~~`qs_build_linked_dashboard`~~ — created by M2.
- ~~`LinkedLane.refreshSource`~~ / ~~`LinkedLane.runSource` (public)~~ — `runSource` is internal; M5 adds `refreshSource`.
- ~~`ToolCall.output`~~ — the field is `result` (`basic.py:27`); the server handler's `"output"` key is its own JSON shape.
- ~~A per-widget refresh HTTP endpoint~~ — refresh is client-side only; `/api/v1/ui/surfaces/{id}/refresh` refreshes all
  sources of a persisted surface and is not used.
- ~~A `Grid` A2UI container or a `refresh` component prop~~ — layout uses Row/Column (`catalog/basic/layout.py:24,39`).
- ~~File-based slug loading in QuerySource~~ — slugs are rows in `public.queries` (F016).
- ~~`polestar_graduates_by_course`~~ — does not exist until M9's seed runs.
- ~~A `{group_by}` placeholder in the base slug SQL~~ — `SELECT {fields} FROM polestar.vw_graduates_directory {where_cond}`;
  QS appends GROUP BY itself (verified live).
- ~~`paged`/`page` pagination keys~~ — parsed but ignored by QS; use `querylimit`/`_offset`.
- ~~A vendored grid.js asset~~ — only unpkg references exist (`parrot/outputs/formats/table.py:181-182`).
- ~~JSONB support in `validate_filter`~~ — rejected today (`InvalidConditionsError: unknown dict operator '@>'`).

### Edit Sites (Blueprint Anchors)

Verified against: `91c9e3e31`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py` | MODIFY | `DIALECT_VERIFIED_AGAINST: str = "4.5.11"` | `dialect.py:20` | 1 |
| same | MODIFY | `DICT_OPERATORS: tuple[str, ...] = (">=", "<=", "<>", "!=", "<", ">")  # sql.pyx:25` | `dialect.py:49` | 1 |
| same | MODIFY | `    operators_dict_form=list(DICT_OPERATORS),` | `dialect.py:95` | 1 |
| same | MODIFY | `                if op not in DICT_OPERATORS:` | `dialect.py:148` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/models.py` | MODIFY | `class DialectReference(BaseModel):` | `models.py:127` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py` | MODIFY | `    def _linked_params(self, detail: SlugDetail, forced: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:` | `toolkit.py:415` | 1 |
| `packages/ai-parrot-tools/tests/querysource/test_toolkit_core.py` | MODIFY | `        "qs_build_linked_surface",` (first list at :18, second at :28) | `:18`, `:28` | 2 |
| `packages/ai-parrot-tools/tests/querysource/test_querysource_floor.py` | MODIFY | `def test_querysource_floor_is_5_1_1() -> None:` | `:11` | 1 |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `db = [` / `    "querysource>=4.1.11",` (:224-225) and `integrations = [` / `    "querysource>=4.1.11",` (:687-688) | `:225`, `:688` | 2 |
| `packages/ai-parrot-tools/pyproject.toml` | MODIFY | `db = ["querysource>=5.1.1", "psycopg-binary>=3.2"]` | `:77` | 1 |
| `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py` | MODIFY | `            series_entry: dict[str, Any] = {` | `echarts.py:279` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.ts` | MODIFY | `  refreshAll(): Promise<void>;` | `index.ts:60` | 1 |
| same | MODIFY | `    async refreshAll() {` | `index.ts:225` | 1 |
| `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UISurface.svelte` | MODIFY | `		refreshAll: () => lane?.refreshAll() ?? Promise.resolve(),` | `:105` | 1 |
| `docs/outputs/a2ui-linked-surfaces.md` | MODIFY | `POST /api/v1/{tenant}/queries/{slug}` | `:44` | 1 |
| same | MODIFY | ``- `querylimit: 500` (capped by toolkit)`` | `:49` | 1 |
| `docs/tools/querysource-toolkit.md` | MODIFY | ``- **`qs_build_linked_surface`** — (FEAT-598) Emits a linked A2UI surface for a query-slug: checks the slug`` | `:64` | 1 |
| `.gitignore` | MODIFY | `!examples/agents/a2ui/**/*.py` | `.gitignore:31` | 1 |
| `packages/ai-parrot-tools/tests/querysource/test_build_linked_dashboard_tool.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/tests/querysource/test_dialect_jsonb.py` | CREATE | — | — | — |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_echarts_pie_names.py` | CREATE | — (siblings: `test_echarts.py`, `test_echarts_props.py`) | — | — |
| `examples/a2ui/server.py`, `dashboard.py`, `client.py`, `seed_by_course.py`, `README.md` | CREATE | — | — | — |
| `examples/a2ui/static/index.html`, `renderer.js`, `linked.js`, `styles.css` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Single-component build path of `build_linked_surface` (`toolkit.py:365-411`). Extract the source construction into
  `_build_linked_source` and reuse it; do not fork the validation rules (`validate_placeholders`, `validate_filter`,
  `reject_variable_values`, forced/locked params).
- Example layout from `examples/clients/voice/server.py` / `examples/forms/form_server.py` (plain `web.Application`,
  `add_static`, `web.run_app`, `auth_exclude_list`).
- Login and `localStorage` from `admin_login_page` (`admin.py:394`, key `ai_parrot_token`).
- Fetch contract from `linked/fetch.ts` and `api/querysource.ts`: port it to JS, do not invent a new one.
- Degrade, don't throw, on unknown components (`degrade.py:46`).
- aiohttp only (never requests/httpx); `self.logger`, never `print`, in library code (the example CLI may print its
  result table).

### Known Risks / Gotchas
- **Production data.** `polestar_graduates_directory` lives in production. Every subagent and sub-shell must use
  `ENV=prod`, reads must stay read-only, and the M9 seed is the only write, behind `--yes`. Never commit tokens,
  passwords or DSNs; the live test and `client.py --check` read credentials from the environment.
- **PBAC.** `env/.env` sets `QS_PBAC_ENABLED=true`, which denies session-less or policy-less requests with a 404. The
  example runs with it off (basic auth only). Another venv's config can still turn PBAC on (seen with the querysource
  checkout venv).
- **AuthHandler needs the user model.** `AuthHandler().setup` imports the configured `AUTH_USER_MODEL`. A wrong value
  fails at startup; the user fixed it in the environment on 2026-09-28.
- **Unstable pagination.** Without `ordering`, QS pages are not deterministic (a different first row on every call).
  The grid always sends `ordering: ["student_uid"]`.
- **NULL buckets.** country (1) and licensee (7103 rows) have NULL groups; label them "Unassigned" in both renderers.
- **People vs diplomas.** KPIs count people (9191 Studio); the pie counts diplomas (9204). Label accordingly.
- **Snapshot size.** Snapshots are capped at 500 rows per source; the grid is live-paged, never snapshot-only.
- **Agent determinism.** The agent must call the tool exactly once with `WIDGETS`. `extract_envelope` fails loudly
  otherwise, and the cached envelope avoids re-running the LLM per page load.
- **Svelte untested so far.** The FEAT-598 Svelte lane never ran real vitest/svelte-check (F008). M5 must run
  `pnpm vitest` and `svelte-check`.
- **Shared venv.** It must stay at querysource ≥5.1.2 (operator action; never `uv sync` from a worktree).

### Follow-ups (not in this feature — `querysource` repo)
- **QS-1** — a JSONB array-length filter operator (e.g. `{"graduation_details": {"jsonb_array_length>": 1}}`). It would
  replace the multi-graduate KPI's `count(*) FILTER (...)` expression inside `fields`.
- **QS-2** — `group_by`/`fields` over JSONB array element keys (e.g. `"graduation_details[].course"` → LATERAL
  `jsonb_array_elements`). It would retire `polestar_graduates_by_course`.
- Then a small ai-parrot follow-up moves `WIDGETS` to the new syntax and drops the seed.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `querysource` | `>=5.1.2` | JSONB `@>`, working tenant routes, `/api/v1/queries/{schema}/{slug}` alias |
| `echarts` (JS) | vendored `formats/assets/echarts.min.js` | charts (already shipped) |
| `gridjs` (JS) | `6.2.0` via unpkg + SRI | grid (already referenced by `formats/table.py`, `interactive/catalog/libraries/gridjs.md`) |

---

## 8. Open Questions

- [x] How is the course pie fed? — *Resolved in proposal*: a second seeded slug `polestar_graduates_by_course` (interim;
  QS-2 follow-up).
- [x] Which auth backend? — *Resolved in proposal*: real BasicAuth via AuthHandler; JWT in `localStorage`; no PBAC
  policy, basic authentication only.
- [x] How is the surface generated and served? — *Resolved in proposal*: an agent plus the example's own endpoint; a
  multi-widget dashboard tool (TOOL origin); BotManager optional.
- [x] Core-change scope? — *Resolved in proposal*: the dashboard helper, the querysource pin (now ≥5.1.2), the pie +
  wire-doc fixes, and per-widget refresh in the TS lane.
- [x] Refresh granularity? — *Resolved in proposal*: per widget, plus "Refresh all".
- [x] querysource version? — *Resolved in proposal*: ≥5.1 is required (FEAT-598's changes live there); 5.1.2 fixes the
  routes and adds the alias.
- [x] Where does the slug live? — *Resolved in proposal*: prod `public.queries`, data in schema `polestar`; always
  `ENV=prod`.
- [x] Grid with 17k rows? — *Resolved in proposal*: server-side paging.
- [x] Which LLM does the dashboard agent use by default (`--llm`)? — *Resolved by Jesus Lara (2026-09-29)*: Anthropic
  Sonnet 5 — `--llm` defaults to `anthropic:claude-sonnet-5`.
- [x] Free-text search in the grid? — *Resolved by Jesus Lara (2026-09-29)*: column filters only; no free-text search.
- [x] Seed mechanism for `polestar_graduates_by_course`? — *Resolved by Jesus Lara (2026-09-29)*: a SQL upsert into
  `public.queries` (copying the base row's columns), not the QS management API.

---

## 9. Design Research Cross-Check

> Model: gpt-5.6-luna (codex-cli 0.157.0, reasoning high) · Status: completed · Transcript: `sdd/state/FEAT-610/design_research/`

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Compose a rooted A2UI tree, not a flat widget list (architecture) | CONFIRM | Already designed as root Column; made reachability an explicit rule and test. | §3 M2, §4 |
| S2 | Keep the 17k-row grid outside the normal linked-frame path (architecture) | CONFIRM | Paging is example-only (`fetchPage` in `static/linked.js`), not a wire-contract change; admin DataTable stays bounded. | §3 M8 |
| S3 | Typed dashboard helper; validate bindings before execution (api) | CONFIRM | `DashboardWidget` model already typed; added component-type limit and explicit KPI aggregate column. | §3 M2 |
| S4 | Refresh at the source boundary, ownership from bindings (api) | CONFIRM | Key resolved from the widget binding; browser never sends slug/conditions; in-flight dedup per key. | §3 M5 |
| S5 | Do not parallelize refresh-all across dependent sources (risk) | CONFIRM | `refreshAll` keeps dependency order; `refreshSource` re-runs transform dependents in order. | §3 M5 |
| S6 | Update every resolver and lock the QuerySource version (risk) | CONFIRM | Verified `uv.lock:13047` pins 5.1.1; M3 now regenerates the lock with `uv lock` (exclusive). | §3 M3, Worktree Strategy |
| S7 | Treat grid.js as an unresolved asset dependency (risk) | CONFIRM | Real sha384 SRI computed from the pinned files; catalog placeholders not copied. Vendoring rejected by the user's no-new-library constraint. | §3 M8 |
| S8 | Contract tests for pie slice shape and dashboard reachability (testing) | CONFIRM | Pie test already in §4 (M4); reachability test added. | §4 |
| S9 | Move course-slug creation out of application startup (risk) | CONFIRM | Premise already met (seed is a separate `--yes` command); added a read-only startup slug check that degrades the widget. | §3 M7 |
| S10 | Exact example whitelist and a tracked-file assertion (risk) | CONFIRM | Added `git check-ignore` validation to the whitelist. | §3 M9 |

Summary: **10** confirmed · **0** rejected · **0** escalated. All `affected_paths` passed containment and `test -e`.

---

## Worktree Strategy

- **Isolation**: one feature worktree `feat-FEAT-610-a2ui-linked-e2e-test` from `origin/dev`; the `sdd-coder` engine
  gives each task its own sub-worktree.
- **Module dependency graph**:
  - M2 → M1 (the dashboard tool validates `@>` filters through `validate_filter`);
  - M6 → M1, M2, M5 (the docs describe them);
  - M7 → M2 (it calls `qs_build_linked_dashboard`);
  - M8 → M7 (it consumes `/api/a2ui/dashboard`);
  - M9 → M7, M8.
  - M1, M3, M4 and M5 have no edges and can run concurrently.
- **Shared files**: `packages/ai-parrot-tools/src/parrot_tools/querysource/models.py` (M1 `DialectReference`, M2
  `DashboardWidget`) → serialize M1 before M2; `test_toolkit_core.py` (M1 version assert, M2 tool list) → same
  ordering.
- **Exclusive resources**:
  - M3 edits `pyproject.toml` files and regenerates `uv.lock` → `parallel: false`. Only `uv lock`; never `uv sync`
    inside the worktree.
  - M9's seed writes to production and only runs by hand with `--yes`; it is not part of any automated task step.
- **Cross-feature dependencies**: FEAT-598 (merged). querysource 5.1.2 must be installed in the shared venv (done
  2026-09-28).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-28 | Jesus Lara | Initial draft from the FEAT-610 proposal (research + live verification F040–F042) |
| 0.2 | 2026-09-29 | Jesus Lara | §8 resolved (Sonnet 5, column filters, SQL upsert); codex design research folded (10 confirmed); status approved |
