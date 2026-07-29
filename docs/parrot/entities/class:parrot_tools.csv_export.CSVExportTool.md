---
type: Wiki Entity
title: CSVExportTool
id: class:parrot_tools.csv_export.CSVExportTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: CSV Export Tool for exporting structured data to CSV files.
relates_to:
- concept: class:parrot_tools.document.AbstractDocumentTool
  rel: extends
---

# CSVExportTool

Defined in [`parrot_tools.csv_export`](../summaries/mod:parrot_tools.csv_export.md).

```python
class CSVExportTool(AbstractDocumentTool)
```

CSV Export Tool for exporting structured data to CSV files.

This tool exports pandas DataFrames, lists of dictionaries, or JSON data
to CSV files with configurable formatting options.

Features:
- Export DataFrames to CSV with custom delimiters
- Support for various encodings (UTF-8, Latin-1, etc.)
- Configurable quoting behavior
- Date and float formatting options
- Column selection and filtering
- Missing value representation
- BOM support for Excel compatibility

Example:
    tool = CSVExportTool()
    result = await tool.export_data(
        data=[{"name": "John", "age": 30}, {"name": "Jane", "age": 25}],
        delimiter=";",
        encoding="utf-8-sig"  # With BOM for Excel
    )

## Methods

- `async def export_dataframe(self, dataframe: pd.DataFrame, **kwargs) -> Dict[str, Any]` — Convenience method to directly export a DataFrame.
- `async def export_data(self, data: Union[List[Dict], pd.DataFrame, str], **kwargs) -> Dict[str, Any]` — Convenience method to export various data formats.
- `async def export_to_tsv(self, data: Union[List[Dict], pd.DataFrame, str], **kwargs) -> Dict[str, Any]` — Export data to TSV (Tab-Separated Values) format.
- `async def export_for_excel(self, data: Union[List[Dict], pd.DataFrame, str], **kwargs) -> Dict[str, Any]` — Export data to CSV with Excel-compatible settings.
- `async def quick_export(self, data: Union[pd.DataFrame, List[Dict], str], filename: Optional[str]=None) -> str` — Quick export method that returns just the file path.
- `def get_format_info(self) -> Dict[str, Any]` — Get information about supported CSV options.
