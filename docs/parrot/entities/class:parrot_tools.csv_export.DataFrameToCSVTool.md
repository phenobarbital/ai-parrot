---
type: Wiki Entity
title: DataFrameToCSVTool
id: class:parrot_tools.csv_export.DataFrameToCSVTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Simplified CSV tool focused on DataFrame export.
relates_to:
- concept: class:parrot_tools.csv_export.CSVExportTool
  rel: extends
---

# DataFrameToCSVTool

Defined in [`parrot_tools.csv_export`](../summaries/mod:parrot_tools.csv_export.md).

```python
class DataFrameToCSVTool(CSVExportTool)
```

Simplified CSV tool focused on DataFrame export.

This is a convenience wrapper around CSVExportTool for users who
primarily need to export DataFrames without complex configuration.

## Methods

- `async def simple_export(self, data: Union[pd.DataFrame, List[Dict], str], filename: Optional[str]=None, delimiter: str=',') -> str` — Simple export method with minimal options.
