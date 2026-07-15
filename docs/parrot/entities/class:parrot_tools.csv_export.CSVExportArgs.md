---
type: Wiki Entity
title: CSVExportArgs
id: class:parrot_tools.csv_export.CSVExportArgs
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Arguments schema for CSV export.
relates_to:
- concept: class:parrot_tools.document.DocumentGenerationArgs
  rel: extends
---

# CSVExportArgs

Defined in [`parrot_tools.csv_export`](../summaries/mod:parrot_tools.csv_export.md).

```python
class CSVExportArgs(DocumentGenerationArgs)
```

Arguments schema for CSV export.

## Methods

- `def validate_content(cls, v)` — Validate that content is not empty.
- `def validate_delimiter(cls, v)` — Validate delimiter is a single character.
- `def validate_quote_char(cls, v)` — Validate quote_char is a single character.
