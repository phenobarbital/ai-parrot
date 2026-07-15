---
type: Wiki Entity
title: ExcelStructureAnalyzer
id: class:parrot.tools.dataset_manager.excel_analyzer.ExcelStructureAnalyzer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Core analysis engine for Excel workbooks.
---

# ExcelStructureAnalyzer

Defined in [`parrot.tools.dataset_manager.excel_analyzer`](../summaries/mod:parrot.tools.dataset_manager.excel_analyzer.md).

```python
class ExcelStructureAnalyzer
```

Core analysis engine for Excel workbooks.

Uses ``openpyxl`` to scan sheets and discover table structures via
header-row heuristics (3+ non-empty cells with 40 %+ strings and
numeric data below).

Args:
    path: Path to the Excel file.

## Methods

- `def analyze_workbook(self) -> Dict[str, SheetAnalysis]` — Analyze all sheets and return a mapping of sheet name → SheetAnalysis.
- `def extract_table_as_dataframe(self, sheet_name: str, table: DetectedTable, include_totals: bool=True) -> pd.DataFrame` — Extract a detected table as a clean pandas DataFrame.
- `def extract_cell_range(self, sheet_name: str, cell_range: str) -> List[List[Any]]` — Read raw cell values from an arbitrary Excel-style range.
- `def close(self) -> None` — Close all open workbooks.
