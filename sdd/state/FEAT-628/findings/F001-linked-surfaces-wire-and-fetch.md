# F001 — Linked surfaces (FEAT-598): wire format and fetch path

- **Query**: Q001 (wiki_query) + wiki_page `file:docs/outputs/a2ui-linked-surfaces.md` (score 1.00)
- **Citations**: `docs/outputs/a2ui-linked-surfaces.md` §1–§5

FEAT-598 is **implemented and documented** (tasks TASK-3780 executor, TASK-3785 toolkit,
TASK-3791 e2e, TASK-3796 docs all completed; FEAT-611 validated it live end-to-end).

- A linked surface carries `metadata.extensions.parrot_data_sources`: per data-model
  root key, a `LinkedDataSource` descriptor `{slug, tenant, conditions, request, params,
  locked, refresh, transform, target, snapshot_*, is_multiquery, multi_output}`.
- **Fetch path is client-side and direct to QuerySource**: the renderer POSTs
  `/api/v3/queries/{slug}` / `/api/v1/{tenant}/queries/{slug}` (+ alias/service routes)
  with the **viewer's JWT**. `querylimit` capped at 5000 (`DEFAULT_MAX_FETCH_ROWS`).
- Refresh is client-side per source (`LinkedLane.refreshSource`); there is **no
  per-widget server HTTP endpoint** — only a surface-level server refresh lane (F003).
- Transforms today (§5): (1) inline **DSL v1** — ten ops: select, rename, filter,
  group_by, sort, limit, derive, pivot, join, union; (2) **`transform.ref`** —
  catalogued renderer JS module `name@version` with SRI pin (CSP is the host's job).
- Trust model: `locked` is UX, security is QuerySource PBAC; server lanes fail closed
  without a data-plane guard (`LinkedGuardRequired` → 403); owner-check resource is
  `source:read` on `query_slug:<tenant|public>:<slug>`.
