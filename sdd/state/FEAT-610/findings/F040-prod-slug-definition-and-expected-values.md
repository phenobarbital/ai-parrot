---
id: F040
query_id: Q040
type: read
intent: verify polestar_graduates_directory definition and expected widget values (ENV=prod, read-only)
executed_at: 2026-09-28T21:40:00Z
parent_id: F016
depth: 1
---
# F040 — Prod slug definition + expected widget values

## Summary
Read-only lookup against production (`ENV=prod`, per user instruction) of `public.queries` and the
underlying view. The slug SQL is `SELECT {fields} FROM polestar.vw_graduates_directory {where_cond}`;
default `fields` are 7 columns (student_uid, full_name, city, state, country, graduation_details,
is_requalified), provider `db`, program `polestar`. Data lives in schema `polestar`. The view has
both `licensee` and `graduation_details` columns. `polestar_graduates_by_course` does not exist yet.
There is no `{group_by}`/`{grouping}` placeholder in the SQL — whether QS appends GROUP BY after
`{where_cond}` must be verified live.

## Citations
- path: `public.queries` (prod DB row `query_slug='polestar_graduates_directory'`)
  lines: -
  symbol: `query_raw`
  excerpt: |
    SELECT {fields} FROM polestar.vw_graduates_directory
    {where_cond}
- path: `polestar.vw_graduates_directory` (prod view)
  lines: -
  symbol: -
  excerpt: |
    total rows                                   17572
    jsonb_array_length(graduation_details) > 1   2884
    graduation_details @> [{course:Pilates Studio}]  9191  (people)
    graduation_details @> [{course:Pilates Mat}]     6245  (people)
    distinct country 94 · distinct licensee 22
    by course (diplomas, LATERAL jsonb_array_elements):
      Pilates Studio 9204 · Pilates Mat 6247 · Pilates Rehab 3300 · Pilates Reformer 2048 · NULL 1

## Implications
- `{fields}` placeholder confirms aggregates via payload `fields` work (C8 → high).
- KPI counts people; the course pie counts diplomas — values differ (9191 vs 9204) by design.
- Grid must pass explicit `fields` if it wants columns beyond the 7 defaults (e.g. licensee).
- Pie slug must drop/label the NULL course bucket.
