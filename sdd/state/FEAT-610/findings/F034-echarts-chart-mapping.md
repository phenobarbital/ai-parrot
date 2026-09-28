---
id: F034
query_id: Q030
type: read
intent: How a Chart component maps to an ECharts option (reusable mapping + pie gap)
executed_at: 2026-09-28T18:24:17Z
parent_id: null
depth: 0
---
# F034 — EChartsRenderer._build_option: Chart props → ECharts option (pie slices lose names)
## Summary
`EChartsRenderer._build_option(props)` takes a BAKED Chart dict (`data` already resolved to row dicts) and builds: `title`, `legend`, `xAxis{type:category,data:[row[x]]}`, `yAxis{type:value}` and one series per y column (`{name: col, type: _SERIES_TYPE[type], data: [row[col]...]}`), with stacked/area/donut radius/dual axis/splitSeries/trendline/palette/colorBySign handling; gauge/funnel/treemap/heatmap/waterfall/radar have dedicated row-native builders. For `pie`, the same per-y loop is used and axes are skipped — series data is a flat scalar list, so **slice names (the x categories) are never attached** (`{name,value}` pairs are not built); a pie-by-course would render unlabeled slices. The UI package already depends on `echarts ^5.0.0` and the Python side vendors `echarts.min.js`; the interactive toolkit catalog pins echarts@5.4.3 from jsDelivr with an SRI hash.
## Citations
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py`
  lines: 73-88
  symbol: `_ECHARTS_JS_PATH`, `_SERIES_TYPE`
  excerpt: |
    _ECHARTS_JS_PATH = Path(__file__).parent.parent / "formats" / "assets" / "echarts.min.js"
    _SERIES_TYPE = {"bar": "bar", "line": "line", "area": "line", "scatter": "scatter",
        "pie": "pie", "donut": "pie", "radar": "radar", ...}
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py`
  lines: 274-287
  symbol: `EChartsRenderer._build_option`
  excerpt: |
    for index, col in enumerate(y_cols):
        values = [row.get(col) for row in rows if isinstance(row, dict)]
        series_entry = {"name": col, "type": _SERIES_TYPE.get(mark, series_type), "data": values}
        if chart_type == "donut":
            series_entry["radius"] = ["40%", "70%"]
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/echarts.py`
  lines: 346, 361-367
  symbol: `EChartsRenderer._build_option`
  excerpt: |
    if series_type != "pie":
        ...
        x_axis: dict[str, Any] = {"type": "category", "data": categories}
        y_axis: dict[str, Any] = {"type": "value"}
- path: `packages/ai-parrot/src/parrot/tools/interactive/catalog/libraries/echarts.md`
  lines: 1-9
  symbol: `-`
  excerpt: |
    name: echarts
    url: https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js
    sri_hash: sha384-BQKzmHvQLMCAnL3UtDBA1Al5tFjsCz1wrMlIUA1wkzo14DYkRWjywW+p9pCj0cwd
    global_var: echarts
- path: `packages/ai-parrot-server/ui/package.json`
  lines: 40
  symbol: `dependencies.echarts`
  excerpt: |
    "echarts": "^5.0.0",
## Implications
- The JS renderer needs its own Chart→option mapper (port of `_build_option`), fixing pie/donut to emit `data: rows.map(r => ({name: r[x], value: r[y0]}))`; consider fixing the Python mapper too (ledger candidate).
- Re-running the mapper on each refresh (new rows) + `chart.setOption(opt, {notMerge:true})` is the natural refresh path.
- CDN choice: jsDelivr echarts@5.4.3 with a known SRI hash is already sanctioned in-repo; the vendored bundle is the offline alternative.
