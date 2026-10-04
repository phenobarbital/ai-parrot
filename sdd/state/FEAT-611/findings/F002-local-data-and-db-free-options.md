---
id: F002
query_id: Q002
type: glob
intent: bundled sample data and DB-free options
executed_at: 2026-09-28T20:32:00Z
parent_id: null
depth: 0
---
# F002 — Local data + DB-free options

## Summary
Bundled: plotly gapminder (1704 rows; country, continent, year, lifeExp, pop, gdpPercap, iso_alpha), tips, sklearn iris/wine; seeded synthetic generators examples/agents/a2ui/synthetic_data.py and flex_synthetic_data.py (flex demo explicitly skips slug registration: "slug data is prod-only"). QS has no sqlite/duckdb provider; multi-query "files" source reads local CSV but descriptor needs a slug (kind query_slug) so it must be saved as multiquery slug (DB write). DB-free route = patch _get_qs/_get_multiqs + QueryModel/AsyncDB as the E2E test does, and serve /api/v3/queries/{slug} from the example (pandas/duckdb over CSV).

## Citations
- path: `examples/agents/a2ui/synthetic_data.py`
  lines: 38, 79
- path: `examples/agents/a2ui/flex_synthetic_data.py`
  lines: 16-261
- path: `examples/agents/a2ui/flex_dashboard_demo.py`
  lines: 16, 407-409
- path: `.gitignore`
  lines: 26-28
  symbol: examples/agents/a2ui whitelist
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/models.py`
  lines: 196-197
  symbol: kind Literal["query_slug"]
- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py`
  symbol: `_get_qs`, `_get_multiqs`
- path: `packages/ai-parrot-server/tests/integration/test_linked_surfaces_e2e.py`
  lines: 203-297
- path: `venv:querysource/queries/multi/sources/file.py`
  lines: 21-105
