---
id: F003
query_id: Q003
type: read
intent: Determine which component types can be linked and how each widget carries its query binding
executed_at: 2026-09-28T18:21:06Z
parent_id: null
depth: 0
---
# F003 — Linkable components: Chart, DataTable, KPICard (binding shapes + axis validation)
## Summary
Only three component types are validated/bound: `Chart` and `DataTable` bind `data: {"path": "/<key>/rows"}`;
`KPICard` binds `value: {"path": "/<key>/rows/0/<column>"}` (first row, one column). Axes are validated against the
real fetched frame: Chart `x` must exist and every `y` must be numeric/bool; DataTable `columns[].name` must
exist; KPICard's value column must exist. The widget itself carries NO query — the query lives in the
surface-level descriptor keyed by the same root key; the link is purely the JSON pointer. A pie chart is just
`Chart` with `type` (library shapes like ECharts pie pairs are explicitly the renderer adapter's job). Layout
components (`Column`/`Row`) and FilterBar are allowed alongside but are not bound.
## Citations
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py`
  lines: 477-511
  symbol: `_validate_axes`
  excerpt: |
    binding = component.get("data") if component_type in {"Chart", "DataTable"} else component.get("value")
    ...
    if component_type == "Chart":
        validate_column("x", component.get("x"))
        ... validate_column("y", column, numeric=True)
    elif component_type == "DataTable":
        ... validate_column("columns.name", column.get("name"))
    elif component_type == "KPICard" and value_column is not None:
        validate_column("value", value_column)
- path: `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py`
  lines: 442-455
  symbol: `QuerysourceToolkit._bind_component`
  excerpt: |
    if component_type in {"Chart", "DataTable"}:
        comp["data"] = {"path": f"/{key}/rows"}
    elif component_type == "KPICard":
        value = comp.get("value")
        if isinstance(value, str):
            comp["value"] = {"path": f"/{key}/rows/0/{value}"}
    else:
        raise InvalidConditionsError("component must be one of Chart, DataTable, or KPICard")
## Implications
- KPI hero cards need one source per KPI (or one source whose first row holds several aggregate columns, each KPICard pointing at a different column) — aggregation must be done by the slug's grouping or a `group_by` DSL op.
- Pie/bar distinction is the Chart `type` prop; the HTML renderer must map Chart{type,x,y,rows} → ECharts options itself.
- "Per-widget refresh" maps naturally to "one source per widget" since refresh granularity is the source.
