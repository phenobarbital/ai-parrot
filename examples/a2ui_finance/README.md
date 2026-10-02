# A2UI Finance Linked Dashboard Example

The finance twin of [`examples/a2ui/`](../a2ui/README.md): a linked A2UI dashboard over two QuerySource slugs seeded
on `troc.finance_projection` (the daily budget-variance table behind `agents/finance_reporter.py`). It demonstrates
three things the Polestar example does not:

1. **Definition-only surface.** The agent builds the dashboard with `snapshot=false` (now the toolkit default) and
   the server additionally strips any baked rows (`ensure_definition_only`). The envelope carries the widgets and
   the `parrot_data_sources` descriptors only (`rows: []`, `snapshot_at: null`); the browser lane fetches every
   source exactly once on mount. The toolkit only *probes* each slug with `querylimit=1` to validate columns, so no
   query runs twice.
2. **Single-query route.** The lane posts single slugs to `POST /api/v2/services/queries/{slug}` (QueryService, the
   optimised single-query handler) instead of the MultiQS pipeline route `/api/v3/queries/{slug}`, which is kept only
   for `is_multiquery` descriptors.
3. **Backend verification through `DatasetManager`.** `finance_client.py --check` computes the expected KPI / chart
   values in-process with `DatasetManager.add_query(query_slug=…)` + `materialize(...)` (pandas aggregation) and
   compares them with what the lane fetched over HTTP. Nothing is hard-coded: finance data drifts daily.

## Prerequisites

- **ENV=prod** — the slugs read production data; the table `troc.finance_projection` must exist with rows.
- **querysource ≥ 5.1.2**.
- **QS_PBAC_ENABLED=false** for local development.

## Run order

1. **Seed the two slugs** into `public.queries` (one-time, idempotent; `--dry-run` prints the rows first):
   ```bash
   ENV=prod python examples/a2ui_finance/seed_finance.py --dry-run
   ENV=prod python examples/a2ui_finance/seed_finance.py --yes        # --program troc --program-id N to override
   ```
   `finance_projection_snapshots` = every row; `finance_projection_latest` = rows of the latest `snapshot_date`.
   Both cast the money columns to `float8` inside the SQL so `sum(...)` in `fields` comes back numeric.

2. **Start the server** (port 5001 so it can run next to the Polestar example):
   ```bash
   ENV=prod QS_PBAC_ENABLED=false python examples/a2ui_finance/finance_server.py --port 5001
   ```
   Startup logs a warning naming the seed command when a slug is missing, and a second one when the
   `DatasetManager` probe cannot run the slug (the `--check` client would fail the same way).

3. **Open in the browser** or **run the check**:
   ```bash
   python examples/a2ui_finance/finance_client.py --open --base-url http://localhost:5001
   ENV=prod python examples/a2ui_finance/finance_client.py --check --base-url http://localhost:5001
   ENV=prod python examples/a2ui_finance/finance_client.py --check --no-expect --base-url http://localhost:5001
   ```
   `--check` also asserts the envelope is definition-only and exercises the grid's server paging (stable
   `ordering: [division, project]`, `count(*)` total, a `division` filter).

## Widgets

| key | slug | request | component |
|---|---|---|---|
| `kpi_rev_actual` / `kpi_rev_budget` | latest | `sum(rev_actual)` / `sum(rev_budget)` | KPICard |
| `kpi_rev_variance` / `kpi_ebitda_variance` | latest | `sum(actual) - sum(budget)` | KPICard |
| `by_division` | latest | grouped by `division` | bar chart, actual vs budget |
| `by_project` | latest | grouped by `project` | pie chart |
| `trend` | snapshots | grouped by `snapshot_date` | line chart, actual vs budget |
| `latest_rows` | latest | 7 columns, `ordering: [division, project]`, `limit: 500` | server-paged DataTable |

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ENV` | Yes | `prod` for production data |
| `QS_PBAC_ENABLED` | Yes | `false` for local dev |
| `A2UI_USER_USERNAME` | No | Login user for `--check` (default `admin`) |
| `A2UI_USER_PASSWORD` | For `--check` | Login password (read from `env/<ENV>/.env`) |
| `A2UI_DEMO_PASSWORD` | No | Password override |

## Files

- `finance_dashboard.py` — slugs, widgets, the agent, `extract_envelope` and `ensure_definition_only`.
- `seed_finance.py` — idempotent upsert of both slugs (advisory lock per slug, `--yes` guard, `--dry-run`).
- `finance_server.py` — aiohttp app: QuerySource routes, `GET /api/a2ui/dashboard`, the shared static lane.
- `finance_client.py` — `--open` / `--check`; expectations from `DatasetManager`.
- `static/index.html` — the page; `linked.js`, `renderer.js` and `styles.css` are served from `examples/a2ui/static`.

## Testing

```bash
PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src:packages/ai-parrot-server/src:packages/ai-parrot-visualizations/src:. \
  pytest tests/examples -q -k finance
PARROT_TEST_QS_LIVE=1 ENV=prod pytest tests/examples/test_a2ui_finance_dashboard_live.py -q   # opt-in, production
```
