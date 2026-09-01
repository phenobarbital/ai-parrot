---
name: widget
description: >
  Export a single Flex KPI (Payroll Contribution, Pay Code, Rep
  Utilization, or Proximity Staffing) as an A2UI structured chart / map /
  table / hero-card envelope for frontend rendering — always via the
  registered transformer that already computes the KPI, never a
  hand-rolled aggregation.
triggers: ["/widget"]
category: domain
version: "1.0"
---

# /widget — Export a Flex KPI as a Structured A2UI Envelope

You are asked to export ONE named KPI so the frontend can render it as a
standalone widget (chart, map, table, or hero card). Every number MUST
come from the KPI's registered `agents/flex_dashboard/transformers.py`
function — never recomputed inline with pandas ad-hoc code.

## How to use this skill

1. **Identify the KPI** from the user's request (e.g. "worked hours by
   month", "proximity staffing", "payroll % to revenue"). If ambiguous,
   ask which one — do not guess.
2. **Read `kpi-table.md`** (adjacent asset) for the exact transformer
   name, its required dataset alias(es), the recipe data-model path the
   dashboard binds it to, and which A2UI output mode it maps to.
3. **Run the transformer's data** via the agent's normal tools
   (`python_repl_pandas` over the registered datasets, or
   `dataset_fetch_dataset` to materialize a lazy alias first) — reproduce
   exactly what the transformer computes, using
   `agents/flex_dashboard/normalize.py` for any currency/date/column
   cleaning, same as the transformer itself does.
4. **Emit the matching structured output mode** (see `kpi-table.md`):
   - Month-series KPIs → `STRUCTURED_CHART` (line chart, x=`month`).
   - Pay Code / Rep Utilization tabular KPIs → `STRUCTURED_TABLE`.
   - Proximity Staffing → `STRUCTURED_MAP` (store + employee layers).
   - Hero totals (Worked Hours, Payroll, P&L Revenue, Payroll % to
     Revenue) → a `KPICard`-shaped structured envelope (single value +
     label), one per requested total.
5. If the user named a filter (month, flex_type, pay_code, cost_center,
   category, radius_miles, nearest_n), apply ONLY the filters that KPI's
   own dataset supports (per-section filter rule — see `kpi-table.md`'s
   "Supported filters" column). A filter unsupported by the requested
   KPI's dataset is a no-op for that KPI, never an error.

## Hard rules

1. **Never invent a number.** Every value in the widget must trace back to
   the named transformer's output on the currently registered datasets.
2. **Never widen the KPI's own filter scope.** A `flex_type` filter must
   never narrow a finance-only KPI (Payroll/Revenue/Payroll %); a
   `pay_code` filter must never narrow Rep Utilization or Proximity
   Staffing.
3. **State which filters were applied** in the response alongside the
   widget, so the user can see what the numbers reflect.
4. **Proximity Staffing defaults**: `radius_miles=50`, `nearest_n=3`
   unless the user overrides them.
