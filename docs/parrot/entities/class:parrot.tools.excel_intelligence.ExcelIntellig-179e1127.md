---
type: Wiki Entity
title: ExcelIntelligenceToolkit
id: class:parrot.tools.excel_intelligence.ExcelIntelligenceToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit for intelligent Excel file analysis.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# ExcelIntelligenceToolkit

Defined in [`parrot.tools.excel_intelligence`](../summaries/mod:parrot.tools.excel_intelligence.md).

```python
class ExcelIntelligenceToolkit(AbstractToolkit)
```

Toolkit for intelligent Excel file analysis.

Provides LLM agents with tools to analyze complex Excel workbooks:

1. ``inspect_workbook`` — structural map of sheets and tables
2. ``extract_table`` — clean tabular data for a specific table
3. ``query_cells`` — raw cell values for arbitrary ranges

Analyzers are cached by file path so repeated calls against the same
workbook do not re-parse the file.

## Methods

- `async def inspect_workbook(self, file_path: str, sheet_name: Optional[str]=None) -> str` — Analyze the structure of an Excel workbook.
- `async def extract_table(self, file_path: str, sheet_name: str, table_id: str, include_totals: bool=False, max_rows: int=200, output_format: str='markdown') -> str` — Extract a specific table as clean tabular data.
- `async def query_cells(self, file_path: str, sheet_name: str, cell_range: str) -> str` — Read raw cell values from a specific range.
- `async def cleanup(self) -> None` — Close all cached workbooks and clear caches.
