---
type: Wiki Entity
title: DetectedTable
id: class:parrot.tools.dataset_manager.excel_analyzer.DetectedTable
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A table discovered within a sheet.
---

# DetectedTable

Defined in [`parrot.tools.dataset_manager.excel_analyzer`](../summaries/mod:parrot.tools.dataset_manager.excel_analyzer.md).

```python
class DetectedTable
```

A table discovered within a sheet.

## Methods

- `def excel_range(self) -> str` — Return the full range of the table (header → last data row).
- `def to_summary(self) -> str` — Return a human-readable summary of this table.
