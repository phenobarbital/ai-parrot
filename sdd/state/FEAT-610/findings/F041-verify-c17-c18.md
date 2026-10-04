---
id: F041
query_id: Q041
type: read
intent: verify C17 (pie slices unnamed) by execution and C18 (wire-doc drift) by reading doc vs code
executed_at: 2026-09-28T22:05:00Z
parent_id: F034
depth: 1
---
# F041 — C17 and C18 verified

## Summary
C17: running `EChartsRenderer()._build_option({"type": "pie"|"donut", "x": "course", "y": ["graduates"], "data": rows})`
returns `series[0].data == [10, 5]`: plain values, no `name`, and no xAxis (skipped for pie). ECharts slices
are therefore unlabeled. C18: the wire doc §3 disagrees with the TS lane on three points: the route (it documents only
the tenant route, while the code uses `/api/v3/queries/{slug}` when there is no tenant), the cap (`querylimit: 500` vs
`DEFAULT_MAX_FETCH_ROWS = 5000`), and `refresh` (the doc says "true, never false"; the code sends it only when true
and deletes it otherwise).

## Citations
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py`
  lines: 276-283
  symbol: `EChartsRenderer._build_option`
  excerpt: |
    for index, col in enumerate(y_cols):
        values = [row.get(col) for row in rows if isinstance(row, dict)]
        ...
        series_entry: dict[str, Any] = {
            "name": col,
            "type": _SERIES_TYPE.get(mark, series_type),
            "data": values,
- path: `docs/outputs/a2ui-linked-surfaces.md`
  lines: 39-50
  symbol: -
  excerpt: |
    POST /api/v1/{tenant}/queries/{slug}
    - `refresh: true` (never false)
    - `querylimit: 500` (capped by toolkit)
- path: `packages/ai-parrot-server/ui/src/lib/api/querysource.ts`
  lines: 21-24
  symbol: `queryUrl`
  excerpt: |
    return tenant ? `${baseUrl}/api/v1/${encodeURIComponent(tenant)}/queries/${s}` : `${baseUrl}/api/v3/queries/${s}`;
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/fetch.ts`
  lines: 13, 49-50
  symbol: `DEFAULT_MAX_FETCH_ROWS`, `fetchSource`
  excerpt: |
    export const DEFAULT_MAX_FETCH_ROWS = 5000;
    const body = { ...conditions, querylimit: Math.min(src.request.limit ?? cap, cap) };
    if (body.refresh !== true) delete body.refresh;

## Implications
- Pie fix: build `[{name: row[x], value: row[y]}]` for pie/donut (funnel/treemap already do this, l.537-543).
- The wire-doc fix covers all three points, not just two.
