---
type: Wiki Entity
title: TROCOperationsToolkit
id: class:parrot_tools.troc.tool.TROCOperationsToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: TROC vending operations KPI toolkit.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# TROCOperationsToolkit

Defined in [`parrot_tools.troc.tool`](../summaries/mod:parrot_tools.troc.tool.md).

```python
class TROCOperationsToolkit(AbstractToolkit)
```

TROC vending operations KPI toolkit.

Computes operational KPIs over pre-loaded DataFrames managed by
a DatasetManager instance. All heavy joins (e.g., restock_cycles)
are pre-computed in BigQuery/FlowTask — this toolkit only filters
and aggregates.

Args:
    dataset_manager: DatasetManager with the following datasets registered:
        - kiosks_daily_summary
        - fso_daily_summary
        - restock_cycles
        - employees_weekly (or active_employees_monthly)
        - warehouse_summary

## Methods

- `async def compute_burn_rate(self, filters: Optional[Dict[str, Any]]=None, group_by: Optional[List[str]]=None) -> ToolResult` — Compute inventory burn rate (units depleted per day) for kiosks.
- `async def compute_fill_rate(self, filters: Optional[Dict[str, Any]]=None, group_by: Optional[List[str]]=None) -> ToolResult` — Compute fill rate statistics for kiosks.
- `async def compute_lrw(self, filters: Optional[Dict[str, Any]]=None, group_by: Optional[List[str]]=None, exclude_abandoned: bool=True) -> ToolResult` — Compute Lost Revenue Window (LRW) statistics.
- `async def compute_kmr(self, filters: Optional[Dict[str, Any]]=None, group_by: Optional[List[str]]=None, period: str='latest') -> ToolResult` — Compute Kiosk-Merchandiser Ratio (KMR) per warehouse.
- `async def merchandiser_workload(self, filters: Optional[Dict[str, Any]]=None, group_by: Optional[List[str]]=None) -> ToolResult` — Compute merchandiser workload metrics.
- `async def growth_feasibility(self, warehouse_alias: str, additional_kiosks: int=10, target_max_lrw_hours: float=48.0) -> ToolResult` — Simulate growth feasibility for a warehouse.
- `async def burn_rate_forecast(self, filters: Optional[Dict[str, Any]]=None, group_by: Optional[List[str]]=None, forecast_days: int=7) -> ToolResult` — Forecast when kiosks will reach empty based on current burn rate.
