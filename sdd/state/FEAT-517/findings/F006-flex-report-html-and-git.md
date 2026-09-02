---
id: F006
query_id: Q012+Q013+Q014
type: read+git_log
intent: Target dashboard HTML structure + recent volatility of the A2UI/PandasAgent surface.
executed_at: 2026-09-01T00:00:00Z
depth: 0
---

# F006 — The Flex report HTML is a KPI+filters+map single-file app; A2UI v1 dialect is hot

## Summary

`docs/flex_program_report (39).html` (3064 lines, title "Flex Program Report") is a self-contained page with: a KPI hero row (`kpiRow`: `kpi-avgEmployees`, `kpi-avgHoursShift`, `kpi-avgShiftWorked`, `kpi-employeesWorked`, `kpi-pctWorked`, `kpi-totalShifts`), Chart.js charts (`hoursByMonthChart`, `payrollByMonthChart`, `payCodePieChart`, doughnut/bar/line/bubble), data tables (`hoursByMonthTable`, `payCodeAllocationTable`), a Leaflet-style map (`mapEl`, `mapLegend`, `mapTip`) and a multi-select filter bar (`filterBar`, `msf-date`, `msf-flextype`, `msf-region`, `msf-state`) — i.e. embedded-data client-side filtering by Month/Flex Type/Region/State. Git: the A2UI outputs surface is VERY active in the last 60 days (a2ui-v1-dialect + a2ui-v1-structured-outputs task series: 18-primitive dispatch, interactive-html/echarts/folium on v1 primitives, envelope passthrough); `bots/data.py` also touched recently, including a `wip: info agent` commit (69422348d) — someone has started an infographic-agent WIP on dev.

## Citations

- path: `docs/flex_program_report (39).html`
  lines: 1-3064
  symbol: (ids) `kpiRow, kpi-*, hoursByMonthChart, payrollByMonthChart, payCodePieChart, mapEl, filterBar, msf-date, msf-flextype, msf-region, msf-state`

- path: `packages/ai-parrot-visualizations/src/parrot/outputs/`
  symbol: git_log (60 days)
  excerpt: |
    ff7728a2c feat(a2ui-v1-structured-outputs): TASK-2564 — echarts + folium renderer prop fidelity
    9314cec4a TASK-2563 — satellite _route_envelope dual-emit + map per-layer payloads
    32dfcf854 feat(a2ui-v1-dialect): TASK-2544 — interactive-html, ECharts y Folium sobre primitivas v1.0
    842d9d5b2 TASK-2543 — RendererCapabilities.supported_*, SSR-HTML/PDF v1.0 18-primitive dispatch

- path: `packages/ai-parrot/src/parrot/bots/data.py`
  symbol: git_log (60 days)
  excerpt: |
    69422348d wip: info agent
    051939fae feat(a2ui-v1-structured-outputs): TASK-2565 — agents + transport: artifact v2 call sites
    8134e350e TASK-2219 — Rewrite system prompts for structured-chart/A2UI

## Notes

The KPI ids in the shipped report skew to utilization metrics; the ticket asks for a payroll-contribution hero row (Worked Hours, Payroll, Revenue, Payroll%) — same layout family, different metric set. The filter set in the ticket (Month, Flex Type, Pay Code, Cost Center) differs from the report's (Date, Flex Type, Region, State).
