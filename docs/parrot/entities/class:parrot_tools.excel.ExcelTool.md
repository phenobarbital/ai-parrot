---
type: Wiki Entity
title: ExcelTool
id: class:parrot_tools.excel.ExcelTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Microsoft Excel/OpenDocument Spreadsheet Generation Tool.
relates_to:
- concept: class:parrot_tools.document.AbstractDocumentTool
  rel: extends
---

# ExcelTool

Defined in [`parrot_tools.excel`](../summaries/mod:parrot_tools.excel.md).

```python
class ExcelTool(AbstractDocumentTool)
```

Microsoft Excel/OpenDocument Spreadsheet Generation Tool.

This tool exports pandas DataFrames to Excel (.xlsx) or OpenDocument (.ods) files
with support for custom styling, templates, and advanced formatting features.

Features:
- Export DataFrames to Excel or ODS formats
- Custom header and data cell styling
- Template support for both formats
- Auto-adjusting column widths
- Header row freezing
- Professional spreadsheet formatting
- Comprehensive error handling and validation

## Methods

- `async def export_dataframe(self, dataframe: pd.DataFrame, output_format: Literal['excel', 'ods']='excel', **kwargs) -> Dict[str, Any]` — Convenience method to directly export a DataFrame.
- `async def export_data(self, data: Union[List[Dict], pd.DataFrame, str], output_format: Literal['excel', 'ods']='excel', **kwargs) -> Dict[str, Any]` — Convenience method to export various data formats.
- `def get_format_info(self) -> Dict[str, Any]` — Get information about supported formats.
