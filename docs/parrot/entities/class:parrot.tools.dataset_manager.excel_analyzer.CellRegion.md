---
type: Wiki Entity
title: CellRegion
id: class:parrot.tools.dataset_manager.excel_analyzer.CellRegion
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A rectangular region within a sheet.
---

# CellRegion

Defined in [`parrot.tools.dataset_manager.excel_analyzer`](../summaries/mod:parrot.tools.dataset_manager.excel_analyzer.md).

```python
class CellRegion
```

A rectangular region within a sheet.

## Methods

- `def excel_range(self) -> str` — Return the region as an Excel-style range string (e.g. 'A2:C5').
- `def row_count(self) -> int` — Number of rows in the region.
- `def col_count(self) -> int` — Number of columns in the region.
