---
id: F001
query_id: Q001
type: grep
intent: enumerate referenced query slugs
executed_at: 2026-09-28T20:32:00Z
parent_id: null
depth: 0
---
# F001 — Candidate real slugs (all in shared Postgres public.queries)

## Summary
No slug SQL lives in the repo; columns are inferred from usage. Best candidates: epson_field_activity (placeholders firstdate/lastdate; day, visits, program, store_id) + epson_program_targets (program, target) — already used by linked fixtures; epson_multiquery (result, count); walmart_store_kpis (total_sales, units_sold, goal_percentage) + walmart_regions/districts/stores hierarchy; six flex slugs (flex_msl_brian_bi, Finance_results_bi, flex_hours_query_pbi, flex_empolyees_brian_bi, fm_regions_avg_employees_html, fm_rep_utilization) with offline fakes.

## Citations
- path: `packages/ai-parrot-tools/src/parrot_tools/querysource/dialect.py`
  lines: 97-110
- path: `packages/ai-parrot-tools/tests/querysource/conftest.py`
  lines: 8-47
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/envelopes/linked_chart.json`
  lines: 82
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/envelopes/linked_dashboard_join.json`
  lines: 102, 150
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/envelopes/linked_multiquery_public.json`
  lines: 63
- path: `examples/navigator_walmart_stores.py`
  lines: 101-122, 306-314, 348
- path: `agents/flex_dashboard.py`
  lines: 105-110
- path: `packages/ai-parrot/tests/outputs/a2ui/linked/conftest.py`
  lines: 13-23
  symbol: activity_frame
