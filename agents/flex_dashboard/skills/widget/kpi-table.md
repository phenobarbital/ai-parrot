# Flex KPI → transformer → output mode reference

Every row: KPI name, registered transformer (`agents/flex_dashboard/
transformers.py`), required dataset alias(es), recipe data-model path
(`agents/flex_dashboard.py::FlexDashboard.dashboard_descriptor()`),
A2UI output mode, and supported filters (per-section filter rule).

| KPI | Transformer | Dataset alias(es) | Recipe path | Output mode | Supported filters |
|---|---|---|---|---|---|
| Worked Hours (total) | `payroll_hero` | `hours`, `finance` | `/payroll_hero/worked_hours_total` | `KPICard` hero | none |
| Payroll (total) | `payroll_hero` | `hours`, `finance` | `/payroll_hero/payroll_total` | `KPICard` hero | none |
| P&L Revenue (total) | `payroll_hero` | `hours`, `finance` | `/payroll_hero/revenue_total` | `KPICard` hero | none |
| Payroll % to Revenue (total) | `payroll_hero` | `hours`, `finance` | `/payroll_hero/payroll_pct` | `KPICard` hero | none |
| Worked Hours by Month | `worked_hours_by_month` | `hours` | `/worked_hours_by_month/series` | `STRUCTURED_CHART` | month, pay_code, cost_center |
| Payroll by Month | `payroll_by_month` | `finance` | `/payroll_by_month/series` | `STRUCTURED_CHART` | month |
| P&L Revenue by Month | `revenue_by_month` | `finance` | `/revenue_by_month/series` | `STRUCTURED_CHART` | month |
| Payroll % to Revenue by Month | `payroll_pct_by_month` | `finance` | `/payroll_pct_by_month/series` | `STRUCTURED_CHART` | month |
| Pay Code Hours | `pay_code_hours` | `hours` | `/pay_code_hours/records` | `STRUCTURED_TABLE` | month, pay_code, cost_center |
| Worked Hours by Pay Code Allocation | `pay_code_allocation` | `hours` | `/pay_code_allocation/records` | `STRUCTURED_TABLE` | month, cost_center |
| Rep Utilization by Region | `rep_utilization_by_region` | `rep_utilization`, `region_utilization` | `/rep_utilization_by_region/records` | `STRUCTURED_TABLE` | month, category |
| Proximity Staffing | `proximity_staffing` | `msl`, `employees` | `/proximity_staffing/{store_layer,employee_layer,coverage}` | `STRUCTURED_MAP` | flex_type, radius_miles, nearest_n |

## Notes

- Payroll % to Revenue is ALWAYS `sum(Payroll) / sum(Revenue)` — Revenue ALONE
  as the denominator, never `Revenue + PC Revenue` (spec §2 resolved Q&A,
  regression-pinned by `test_payroll_pct_denominator`).
- Rep Utilization is ALWAYS recomputed as `employees_worked /
  average_active` from `rep_utilization`; `region_utilization`'s
  precomputed `Employee Utilization` is a cross-check value only.
- Proximity Staffing's coverage table lists, per store, the nearest
  `nearest_n` employees by haversine distance and a count of employees
  within `radius_miles`.
