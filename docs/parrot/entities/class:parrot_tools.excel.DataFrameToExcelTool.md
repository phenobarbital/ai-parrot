---
type: Wiki Entity
title: DataFrameToExcelTool
id: class:parrot_tools.excel.DataFrameToExcelTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Simplified Excel tool that focuses purely on DataFrame export.
relates_to:
- concept: class:parrot_tools.excel.ExcelTool
  rel: extends
---

# DataFrameToExcelTool

Defined in [`parrot_tools.excel`](../summaries/mod:parrot_tools.excel.md).

```python
class DataFrameToExcelTool(ExcelTool)
```

Simplified Excel tool that focuses purely on DataFrame export.

This is a convenience wrapper around ExcelTool for users who primarily
need to export DataFrames without complex document features.

## Methods

- `async def quick_export(self, data: Union[pd.DataFrame, List[Dict], str], filename: Optional[str]=None, format: Literal['excel', 'ods']='excel') -> str` — Quick export method that returns just the file path.
