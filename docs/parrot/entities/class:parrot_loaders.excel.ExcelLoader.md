---
type: Wiki Entity
title: ExcelLoader
id: class:parrot_loaders.excel.ExcelLoader
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Excel loader that converts an Excel workbook (or DataFrame) into Documents.
relates_to:
- concept: class:parrot.loaders.abstract.AbstractLoader
  rel: extends
---

# ExcelLoader

Defined in [`parrot_loaders.excel`](../summaries/mod:parrot_loaders.excel.md).

```python
class ExcelLoader(AbstractLoader)
```

Excel loader that converts an Excel workbook (or DataFrame) into Documents.

Supports two output modes:

- ``output_mode="sheet"`` (default): one Document per non-empty sheet,
  using ``ExcelStructureAnalyzer`` for structural context (table detection,
  structural summaries, markdown rendering).
- ``output_mode="row"`` (legacy): one Document per row per sheet — the
  original behaviour preserved for backward compatibility.

Works for ``.xlsx`` / ``.xlsm`` / ``.xls`` files.  Also accepts a
``pandas.DataFrame`` (always falls back to row mode).
