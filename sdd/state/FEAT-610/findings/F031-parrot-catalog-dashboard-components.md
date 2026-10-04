---
id: F031
query_id: Q031
type: read
intent: Catalog definitions for KPICard, Chart, DataTable, FilterBar (dashboard vocabulary)
executed_at: 2026-09-28T18:24:17Z
parent_id: null
depth: 0
---
# F031 — Parrot catalog: KPICard / Chart / DataTable / FilterBar schemas
## Summary
Dashboard vocabulary lives in the Parrot presentation catalog (`catalogId https://parrot.dev/catalogs/v1`, `catalog/parrot/*.py`), each a Python class with a JSON `SCHEMA`, LLM `INSTRUCTIONS` and a `lower()` to Basic primitives. **KPICard**: required `label`,`value`; optional `unit`,`delta`,`trend`(up/down/flat),`icon`,`color`,`comparisonPeriod`,`higherIsBetter`,`format`(percent/currency/number). **Chart**: schema derived from `StructuredChartConfig`; required `type`,`x`,`y` (y = list of value columns = series); rows bound via `data: {"path"}`; plus `title`,`description`,`stacked`,`splitSeries`,`trendline`,`showLegend`,`xAxisMode`,`palette`,`seriesTypes`,`seriesAxes`,`xAxisLabel`,`yAxisLabel(s)`,`layout`(full/half),`colorBySign`... Types: bar/horizontalBar/line/area/scatter/pie/donut/radar/map/gauge/funnel/waterfall/heatmap/treemap. **DataTable**: required `columns[{name,type,title,format}]`, `data` binding, `totalRows`,`truncated`,`explanation`,`style` — no paging/sort/filter props on the wire (paging is renderer policy). **FilterBar**: required `filters[{column,label,options[{label,value}],multiple?,param?{source,name}}]`; `param` (FEAT-598) re-fetches a linked source instead of local filtering.
## Citations
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/kpicard.py`
  lines: 15-54
  symbol: `KPICARD_SCHEMA`
  excerpt: |
    "label": {"type": "string"},
    "value": {"description": "Primary metric value (number, string, or binding)."},
    "unit": ..., "delta": ..., "trend": {"enum": ["up", "down", "flat"]},
    "icon", "color", "comparisonPeriod", "higherIsBetter", "format": ["percent","currency","number"]
    "required": ["label", "value"],
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/chart.py`
  lines: 26-51
  symbol: `CHART_SCHEMA`, `CHART_INSTRUCTIONS`
  excerpt: |
    CHART_SCHEMA = derive_schema(StructuredChartConfig, binding_fields=("data",), required=("type", "x", "y"))
    "Set `type` (bar/line/area/scatter/pie/donut/...), `x` (label column) and `y` (one or "
    "more value columns). ... Bind the row data with "
    '`data: {"path": "/pointer"}` into the data model — never inline large arrays.'
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/datatable.py`
  lines: 27-48
  symbol: `DATATABLE_SCHEMA`
  excerpt: |
    DATATABLE_SCHEMA = derive_schema(StructuredTableConfig, binding_fields=("data",), required=("columns",))
    DATATABLE_SCHEMA["properties"]["style"] = {"enum": ["default","striped","bordered","compact","comparison"]}
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/filterbar.py`
  lines: 29-71
  symbol: `FILTERBAR_SCHEMA`
  excerpt: |
    "column", "label", "options": [{"label","value"}], "multiple": {"type": "boolean"},
    "param": {"description": "Linked surfaces only: re-fetch data source `source` with QuerySource parameter `name` ..."
              "properties": {"source": ..., "name": ...}, "required": ["source", "name"]},
    "required": ["column", "label", "options"],
- path: `docs/frontend/agentdashboard-a2ui-reference.md`
  lines: 497-548
  symbol: `§5.2 Parrot presentation catalog`
  excerpt: |
    #### `Chart` (`chart.py`) — required `type`, `x`, `y`
    **There is no ECharts option on the wire.**
    #### `DataTable` ... Mirror the FEAT-493 rich table: numeric alignment ..., sticky header,
    "showing N of M" when `truncated`, and search + pagination only above 100 rows.
## Implications
- Bar-by-country / bar-by-licensee = `Chart{type:"bar", x:"country", y:["count"], data:{path:"/<src>/rows"}}`; pie-by-course = `Chart{type:"pie", x:"course", y:["count"]}` — one y column = one series.
- No "refresh button" prop exists in any component schema; per-widget refresh must be renderer behaviour keyed off which linked source a widget's `data`/`value` binding points at.
- Paging/search/sort for a 17k-row grid is renderer policy (grid.js options), not wire vocabulary; `totalRows`/`truncated` are the only hints.
- Adding new props would require schema edits (catalog parity tests: `tests/outputs/a2ui/test_catalog_parity.py`); prefer `metadata.extensions.parrot_*` for renderer hints.
