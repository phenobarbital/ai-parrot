---
id: F002
query_id: Q002
type: read
intent: Obtain a real, trimmed linked-surface envelope from the shipped contract fixtures
executed_at: 2026-09-28T18:20:21Z
parent_id: null
depth: 0
---
# F002 — Real wire examples: contract/fixtures/envelopes/*.json
## Summary
Four golden envelopes ship as package data under `parrot/outputs/a2ui/linked/contract/fixtures/envelopes/`
(`linked_chart.json`, `linked_dashboard_join.json`, `linked_no_snapshot.json`, `linked_multiquery_public.json`).
`linked_dashboard_join.json` is the only multi-widget one: a `Column` root with a `Chart` bound to
`/activity/rows` and a `DataTable` bound to `/targets/rows`, two sources, and a `join` transform referencing the
sibling source. Each descriptor is fully materialised (all fields present, `exclude_none=False`): `kind`, `slug`,
`tenant`, `is_multiquery`, `multi_output`, `conditions` (derived cache that is what gets POSTed), `request`
(canonical), `params`, `locked`, `refresh`, `snapshot_at`, `snapshot_truncated`, `target`, `transform`.
No fixture contains a KPICard or FilterBar.
## Citations
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/envelopes/linked_dashboard_join.json`
  lines: 1-40
  symbol: `-`
  excerpt: |
    "catalogId": "https://parrot.dev/catalogs/v1",
    "components": [
      {"children": ["chart","table"], "component": "Column", "id": "root"},
      {"component": "Chart", "data": {"path": "/activity/rows"}, "id": "chart",
       "type": "bar", "x": "day", "y": ["visits"]},
      {"columns": [{"name": "program"},{"name": "target"}], "component": "DataTable",
       "data": {"path": "/targets/rows"}, "id": "table"}
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/envelopes/linked_dashboard_join.json`
  lines: 73-120
  symbol: `-`
  excerpt: |
    "metadata": {"extensions": {"parrot_data_sources": {"activity": {
      "conditions": {"firstdate": "YESTERDAY", "lastdate": "TODAY"},
      "is_multiquery": false, "kind": "query_slug", "locked": [], "multi_output": null,
      "refresh": {"interval_seconds": null, "policy": "on_mount"},
      "request": {"fields": [], "filter": {}, ..., "placeholders": {"firstdate": "YESTERDAY", ...}},
      "slug": "epson_field_activity", "snapshot_at": "2026-09-25T00:00:00Z",
      "snapshot_truncated": false, "target": "/activity/rows", "tenant": null,
      "transform": {"ops": [{"how": "left", "on": [{"left": "program","right": "program"}],
                             "op": "join", "with": "targets"}]}
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/envelopes/linked_chart.json`
  lines: 50-65
  symbol: `-`
  excerpt: |
    "params": {"firstdate": {"accepts_keywords": true, "default": null, "editable": true,
                             "required": false, "type": "date"}, ...}
## Implications
- `linked_dashboard_join.json` is the best template for the example's multi-widget surface and for renderer unit tests; the new example will need its own KPI/pie/grid fixture (none exists).
- A renderer only needs `conditions` (+ `querylimit`) to re-fetch; `request`/`params` matter only for editable filters.
- Other contract data: `contract/schema.json`, `fixtures/dsl/*.json` (17 cases), `fixtures/conditions/*.json` (4 cases) — usable to test a JS executor.
