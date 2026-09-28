---
id: F042
query_id: Q042
type: read
intent: live HTTP check (ENV=prod, read-only) of QS query routes with fields/filter/group_by/paging on a single slug; 5.1.2 route set
executed_at: 2026-09-28T22:40:00Z
parent_id: F011
depth: 1
---
# F042 — Live QS route probe + querysource 5.1.2 routes

## Summary
A minimal aiohttp app with `QuerySource(lazy=False).setup(app)`, no auth, querysource **5.0.0**, `ENV=prod`,
`QS_PBAC_ENABLED=false`. Results for `POST /api/v3/queries/{slug}` and `POST /api/v2/services/queries/{slug}`, which
behaved the same:
- `fields: [count(*) as total]` → 17572
- `count(*) FILTER (WHERE jsonb_array_length(...) > 1)` → 2884
- `group_by: [licensee]` → 23 rows (22 licensees plus a NULL bucket of 7103)
- `_limit`/`_offset` → paged rows
- JSONB `@>` → SQL "syntax error at end of input" (unsupported before 5.1)

QS appends GROUP BY even though the slug SQL has no placeholder. On 5.0.0, `/api/v1/public/queries/{slug}` returned 500:
`tenant.py:244` does `QueryService(request)`, which raises `TypeError: object.__init__()` under navigator-api 4.0.0.

In a second attempt, the 5.1.1 checkout venv returned 404 on every route, because its own config enabled PBAC ("PBAC denied (no
session)"). The authenticated rerun was stopped by the user. The user then upgraded the shared venv to **5.1.2**, which fixes the
routes and adds the alias `/api/v1/queries/{tenant}/{slug}` (e.g. `/api/v1/queries/public/{slug}`); the user's own manual check
of `apple_stores` returned 200 on describe/columns/alias. Not yet re-probed here with `polestar_graduates_directory` on 5.1.2.

## Citations
- path: `venv:querysource/services.py` (5.1.2)
  lines: 407-425
  symbol: -
  excerpt: |
    # Alias: /api/v1/queries/{schema}/{slug} → same tenant handler.
    "/api/v1/queries/{tenant}/{slug}", th.query, allow_head=False
    r = self.app.router.add_post("/api/v1/queries/{tenant}/{slug}", th.query)
- path: `venv:querysource/handlers/tenant.py` (5.0.0, before the upgrade)
  lines: 240-244
  symbol: `TenantQueryHandler.query`
  excerpt: |
    handler = QueryService(request)
    return await handler.query(request)

## Implications
- C6 confirmed: a single slug with fields/filter/group_by/paging works on v3 and v2.
- The pin should be `querysource>=5.1.2`: `@>` plus working tenant routes and the alias.
- The licensee bar needs a label for the NULL bucket (e.g. "Unassigned").
- Remaining check on 5.1.2: `@>` KPIs through the routes with a real bearer token (the first spec task).
