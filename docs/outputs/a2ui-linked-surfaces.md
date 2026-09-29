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

## 3. Fetch path and errors

Renderers fetch linked data by making authenticated requests to QuerySource endpoints:

```
POST /api/v1/{tenant}/queries/{slug}
```

With JWT authentication from the viewer's session. The request includes:
- `refresh: true` (never false)
- `querylimit: 500` (capped by toolkit)
- All other request parameters from the descriptor

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

FEAT-611 validated linked surfaces end to end. It ran as a parallel track to FEAT-610, against staging with
querysource >= 5.1.2. The harness and the full runbook live in
[`examples/agents/a2ui/linked_e2e/`](../../examples/agents/a2ui/linked_e2e/README.md). It covers seeding,
servers, the runner, the pytest tiers and the manual S4 checklist.

| Tier | Command | Role |
|---|---|---|
| Offline | `pytest packages/ai-parrot-server/tests/integration/test_linked_e2e_offline.py`, plus the golden/parity tests and vitest wrappers | Deterministic verdict, with no DB |
| Staging | `ENV=staging pytest -m staging …/test_linked_e2e_staging.py`, or `run_e2e.py` against `server.py` | Live check of S1/S2/S3/S5, staging only |
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
