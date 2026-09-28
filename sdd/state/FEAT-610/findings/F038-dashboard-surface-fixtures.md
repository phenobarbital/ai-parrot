---
id: F038
query_id: Q031
type: glob
intent: Existing test fixtures containing full (dashboard) surface JSON
executed_at: 2026-09-28T18:24:17Z
parent_id: null
depth: 0
---
# F038 — Fixtures: FEAT-598 linked contract envelopes (Chart+DataTable join), goldens per component; no KPI+pie+grid dashboard fixture
## Summary
The only on-disk JSON surfaces with linked sources are the FEAT-598 contract fixtures (bare `createSurface` objects, not version-wrapped): `linked_dashboard_join.json` (root Column → bar Chart + DataTable over two query_slug sources joined via `transform.ops[join]`), `linked_chart.json`, `linked_no_snapshot.json`, `linked_multiquery_public.json`. Per-component lowered goldens (kpicard/chart/datatable/filterbar/filterbar_param...) live in `tests/outputs/a2ui/golden/`. Multi-component dashboards (FilterBar + DataTable + KPICard) exist only as in-code Python envelopes in visualizations tests. No fixture contains KPICard hero cards, a pie chart, and a grid together; grep for `"KPICard"` in any `*.json` returned nothing.
## Citations
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/envelopes/linked_dashboard_join.json`
  lines: 1
  symbol: `-`
  excerpt: |
    {"catalogId": "https://parrot.dev/catalogs/v1", "components": [{"children": ["chart", "table"], "component": "Column", "id": "root"},
     {"component": "Chart", "data": {"path": "/activity/rows"}, "id": "chart", "type": "bar", "x": "day", "y": ["visits"]},
     {"columns": [{"name": "program"}, {"name": "target"}], "component": "DataTable", "data": {"path": "/targets/rows"}, "id": "table"}],
     ... "metadata": {"extensions": {"parrot_data_sources": {"activity": {..., "kind": "query_slug", "refresh": {"interval_seconds": null, "policy": "on_mount"}, ... "slug": "epson_field_activity", "target": "/activity/rows", ...
- path: `packages/ai-parrot/tests/outputs/a2ui/golden/kpicard_lowered.json`
  lines: -
  symbol: `-`
  excerpt: |
    (lowered KPICard golden; siblings: chart_lowered.json, datatable_lowered.json, filterbar_lowered.json, filterbar_param_lowered.json)
- path: `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_filterbar_interactive.py`
  lines: 25-62, 104
  symbol: `_filterbar_and_table_envelope`
  excerpt: |
    Component(id="fb", component="FilterBar", filters=[{"column": "division", "label": "Division", "options": [...], "multiple": True}]),
    Component(id="tbl", component="DataTable", title="Ledger", columns=[...], data={"path": "/rows"}),
    Component(id="k0", component="KPICard", label="Revenue", value=100),
- path: `packages/ai-parrot/tests/outputs/a2ui/linked/test_contract_envelopes.py`
  lines: -
  symbol: `-`
  excerpt: |
    (consumes the contract fixture envelopes above)
## Implications
- `linked_dashboard_join.json` is the best seed for renderer tests (root Column, bound Chart+DataTable, parrot_data_sources with refresh policy); a new FEAT-610 fixture should add KPICards (`/<k>/rows/0/<col>`), pie, and a FilterBar, ideally under the same contract fixtures dir so contract tests validate it.
- JS renderer unit tests (vitest/node) can load these JSON fixtures directly; the Svelte side already does this pattern in `A2UISurface.linked.test.ts`.
