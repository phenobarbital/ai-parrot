# A2UI Linked Surfaces (FEAT-598)

> Surfaces that carry **how to fetch their rows**, not only the rows.

## 1. What a linked surface is

A linked surface is an A2UI envelope that carries data-source descriptors in `metadata.extensions.parrot_data_sources` instead of embedding all rows directly. Each descriptor specifies how to fetch rows from a QuerySource query-slug, including conditions, parameters, and optional transforms. This allows the frontend renderer to re-fetch data dynamically rather than relying solely on static embedded rows.

When a surface includes a snapshot (≤ 500 rows), it is indistinguishable from a regular baked surface to renderers that don't understand the `parrot_data_sources` extension. This ensures backward compatibility with existing renderers.

## 2. Wire format — `metadata.extensions.parrot_data_sources`

The `parrot_data_sources` extension is a mapping keyed by data-model root keys, where each value is a `LinkedDataSource` descriptor:

| Field | Type | Description |
|---|---|---|
| `slug` | string | QuerySource query-slug to execute |
| `tenant` | string/null | Tenant routing (not security) |
| `conditions` | object | Derived cache of request conditions (S5) |
| `request` | SourceRequest | Canonical condition representation |
| `params` | object | User-editable parameter metadata |
| `locked` | string[] | Parameter names forced by the server |
| `refresh` | RefreshPolicy | Renderer refresh policy |
| `transform` | TransformSpec/null | Inline DSL or catalogued module |
| `target` | string | Data-model pointer for binding |
| `snapshot_at` | datetime/null | When snapshot was taken |
| `snapshot_truncated` | boolean | Whether snapshot hit row limit |
| `is_multiquery` | boolean | Whether slug is a MultiQuery pipeline |
| `multi_output` | string/null | Specific output frame for MultiQuery |

The `request` field contains the canonical representation of conditions:
- `placeholders`: Query parameter values
- `filter`: Ad-hoc WHERE clauses
- `fields`: Column projection
- `ordering`: Sort specification
- `grouping`: Group-by columns
- `limit`/`offset`: Pagination

### Source kinds

Every entry carries a `kind` discriminator (a descriptor without one is a `query_slug` source — the shape above):

| `kind` | What it is | Fields |
|---|---|---|
| `query_slug` | A fetched source: one QuerySource call per run | the table above |
| `derived` | A **view computed from a sibling source's frame** with the transform DSL — never fetched, no params, no refresh policy of its own | `from` (sibling key), `transform` (`ops` only; `ref` is rejected), `target`, `snapshot_at`, `snapshot_truncated` |

A derived source is the wire form of "my data comes from the Dashboard": the dashboard fetches `from` once, and
any number of derived views (and any number of components bound directly to `/<from>/rows`) reuse that frame.
Its base is the parent's **full fetched frame** (bounded by the 5000-row fetch cap), never the parent's ≤500-row
snapshot; its own rows are snapshotted like any other source, so bake/HTML lanes and renderers without a lane see
the computed view. Validation (`DATA_SOURCE_INVALID`) requires `from` to name another key of the same surface, a
parent without a `transform.ref`, and no dependency cycle; a FilterBar `parrot_param` may not target a derived key.

## 2b. Linked dashboards — dashboard-owned sources

A dashboard is one linked surface whose sources belong to the *dashboard*, not to its widgets. A widget declares
one of three data origins:

1. **inline** — rows baked into `dataModel[<key>]` with no descriptor (never refreshed);
2. **its own `query_slug` source** — fetched and refreshed independently (the FEAT-610 one-widget-one-source shape);
3. **a dashboard source** — bound directly (`/kpis/rows/0/total_visits` from six KPICards over one `kpis` query that
   computes six aggregates) or through a `derived` view (a grid shows every row of `rows`; a pie chart is
   `{"kind": "derived", "from": "rows", "transform": {"ops": [{"op": "group_by", …}]}}` — a categorical aggregation of
   those same rows computed on the client, with no second call).

`qs_build_linked_dashboard` (see [querysource-toolkit.md](../tools/querysource-toolkit.md)) emits this shape from a
`sources` map plus widgets with `source` / `slug` / `data`. The [Polestar example](../../examples/a2ui/README.md) loads
with 4 QuerySource calls instead of the 8 per-widget calls of its first version.

Refresh semantics, identical on the Python executor, the admin UI lane and the example lane:

| Action | `query_slug` source | `derived` source |
|---|---|---|
| Mount / save-time snapshot | fetched in dependency order, once per pass however many widgets read it | computed after its parent, from the parent's full frame |
| Refresh the dashboard (`refreshAll`, `POST …/refresh {}`) | re-fetched | recomputed through the parent's cascade; never fetched |
| Refresh one shared source (`refreshSource(k)`) | re-fetched, then every query-slug source that (transitively) depends on `k` | every derived view that depends on `k` — through `from`, `join.with` or `union.sources` — recomputed in dependency order |
| Refresh a derived widget (`refreshSource(d)`) | its parent is refreshed | recomputed by the cascade |
| `setParam` / `{"params": {"d": {…}}}` | applied when declared and unlocked | ignored (`source d: ignored params […]` warning); broadcast params never reach derived keys |
| Failure | `error` / `unavailable`, snapshot kept | a parent failure marks its derived views `error` (Python: `data_stage`); a `TransformError` fails only that view and blocks save-time snapshots (502 `data_stage`) |

Caveat: a derived view aggregates what its parent fetched (≤ `max_fetch_rows`, 5000). When the full data set is
larger, put the aggregation in the parent's `request` (`fields` + `grouping`) and derive from that; a server-paged
grid source can never feed a derived view. Note that the DSL `group_by` drops rows whose group key is NULL, whereas
QuerySource `grouping` keeps them as one bucket. `contract/fixtures/parity/derived_dashboard.json` pins the execution
order, the set of fetched keys, the ignored params and the rows every executor must reproduce.

## 3. Fetch path and errors

Renderers fetch linked data by making authenticated requests to QuerySource endpoints:

```
POST /api/v2/services/queries/{slug}            # DEFAULT: no tenant, regular slug → plain QS() (milliseconds)
POST /api/v3/queries/{slug}                     # only when is_multiquery: MultiQS, the one HTTP lane that expands a pipeline
POST /api/v1/{tenant}/queries/{slug}            # tenant store (used by the renderer whenever a tenant is set; kind-aware)
POST /api/v1/queries/{schema}/{slug}            # alias of the tenant route, querysource >= 5.1.2
```

Route rule (`ui/src/lib/api/querysource.ts::queryUrl`, mirrored by `examples/a2ui/static/linked.js` and
`examples/a2ui/client.py`): `tenant` wins; else `is_multiquery` selects v3; else v2. The v3 route is served by
MultiQS, which favours availability over latency (it loads the pipeline definitions, runs in threads and retries
up to 3 times) — it is the data-pipeline/ETL lane, so a regular slug that `QS()` answers in milliseconds must
never go through it. Only a real MultiQuery pipeline needs v3, because v2 executes single-query slugs only.

With JWT authentication from the viewer's session. The request includes:
- `refresh: true` only on a manual refresh; the field is omitted otherwise (never sent as false)
- `querylimit` capped at 5000 rows per fetch (`DEFAULT_MAX_FETCH_ROWS`); `request.limit` may lower it, never raise it
- All other request parameters from the descriptor

An empty result is answered with HTTP 204 (`x-status: Empty Result`) and no body; the lane treats it as zero
rows, never as an error.

### Per-source refresh

Refresh is client-side; there is no per-widget refresh HTTP endpoint. `LinkedLane.refreshSource(key)` re-fetches
one source with `refresh: true` and then re-runs the sources that depend on it (transform dependents), in
dependency order. Concurrent calls for the same key share one in-flight promise. `LinkedLane.refreshAll()`
re-fetches every source sequentially in dependency order (siblings first).

All denials result in 404 "unavailable" responses to prevent information leakage. The renderer shows an appropriate error state to the user.

## 4. Refresh policy and snapshots

Linked surfaces support three refresh policies:
- `on_mount`: Refresh when component mounts (default)
- `manual`: Require explicit user action
- `interval`: Automatic refresh every N seconds (≥ 30s)

While hidden (e.g., in a non-active tab), refresh is paused automatically.

Snapshots embed up to 500 rows directly in the envelope:
- `snapshot_truncated: true` indicates truncation occurred
- Once persisted, snapshots are mandatory (AC16)
- `GET` requests never execute queries; they return the stored snapshot
- While `snapshot_at` is null, show a loading state

## 5. Transforms — DSL v1 and `transform.ref`

Linked surfaces support two types of transforms:
1. Inline DSL operations (ten operations: select, rename, filter, group_by, sort, limit, derive, pivot, join, union)
2. Catalogued renderer modules via `transform.ref` (opaque `name@version` with SRI integrity pin)

The DSL provides lightweight data manipulation without requiring server round trips. Renderer modules offer more sophisticated transformations but require proper CSP configuration by the host page.

## 6. Trust model

- `locked` is not security: It is a UX hint; security is QuerySource PBAC + slug design. Tenant is routing, not security.
- Server lanes run as a trusted service behind a mandatory guard: `LinkedSurfaceService` fails closed without a guard (`LinkedGuardRequired` → 403); owner `principal=` is defense in depth (PBAC can no-op when QuerySource's bootstrap is absent). Document the default wiring (TASK-3805): `BotManager.setup` builds `app["dataplane_guard"]` / injects `bot._dataplane_guard` via `setup_dataplane_guard()` when PBAC initializes (navigator-auth + `PARROT_PBAC_POLICY_DIR`); otherwise linked saves answer 403 until an operator configures PBAC. Owner-check resource naming (confirmed 2026-09-26): `source:read` on `query_slug:<tenant|public>:<slug>`.
- `ref` module CSP is the host page's responsibility: SRI authenticates bytes, not behaviour.

## 7. Share-token viewers

When viewed through a share token, linked surfaces:
- Show only the last snapshot
- Display "data as of `snapshot_at`" 
- Provide a server-side refresh button for authorized users

This ensures that share recipients see consistent data without inadvertently executing queries on their behalf.

## 8. E2E validation

FEAT-611 validated linked surfaces end to end. It ran as a parallel track to FEAT-610, against a live
target (`ENV=staging` or `ENV=dev`; production is always refused) with querysource >= 5.1.2. It uses three
dedicated, seeded E2E slugs: `epson_e2e_activity`, `epson_e2e_targets` and the multiquery
`epson_e2e_activity_vs_targets_mq`. The harness and the full runbook live in
[`examples/agents/a2ui/linked_e2e/`](../../examples/agents/a2ui/linked_e2e/README.md). It covers seeding
(`seed_staging.py seed-sql` / `seed`), servers, the runner, the pytest tiers and the manual S4 checklist.

| Tier | Command | Role |
|---|---|---|
| Offline | `pytest packages/ai-parrot-server/tests/integration/test_linked_e2e_offline.py`, plus the golden/parity tests and vitest wrappers | Deterministic verdict, with no DB |
| Live (staging or dev) | `ENV=dev pytest -m staging …/test_linked_e2e_staging.py`, or `run_e2e.py` against `server.py` | Live check of S1/S2/S3/S5; the `staging` marker means "live target" |
| Manual S4 | Admin UI chat with `epson_linked` in A2UI mode | Exploratory, never required |

`contract/fixtures/parity/epson_dashboard_params.json` pins the conditions and rows that both the Python lane
and the TS lane must reproduce. A SKIP never counts as a PASS.

Core fixes that landed with FEAT-611:

- **Envelope lifting.** A bare CreateSurface is wrapped as `{"version": "v1.0", "createSurface": …}`. The
  bot lifts linked surfaces into the response, and `a2ui_surface_id` goes into `response.metadata`.
- **Admin canvas.** Linked surfaces open a canvas tab (`isLinkedSurface`). `persistedSurfaceId` reaches
  `A2UISurface` from `metadata.a2ui_surface_id`, which enables the server-lane Refresh.
- **TS drift fixes.**
  - `selectFrame` follows the Python rules and throws `FrameSelectionError` on a missing or ambiguous frame.
  - Pivot emits null for missing cells.
  - `deriveConditions` never emits `limit`.
  - `setParam` ignores locked or undeclared names.
  - `serverRefresh` sends the current params and shows `X-Parrot-Refresh-Warnings` as notices.
- **FilterBar param validation.** New codes `FILTER_PARAM_UNKNOWN_SOURCE` and `FILTER_PARAM_UNDECLARED`.
- **`PublishSurfaceTool` guard resolution.** The tool resolves its guard in this order: explicit service,
  `guard` kwarg, `bot._dataplane_guard`, then fail closed.
- **Python left join dtype.** Right-hand columns keep their dtypes when no null-key rows exist, which
  restores Python↔TS parity for `derive` after a join.
- **Dependency floor.** `querysource>=5.1.2`.
