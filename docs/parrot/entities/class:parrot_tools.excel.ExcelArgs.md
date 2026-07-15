---
type: Wiki Entity
title: ExcelArgs
id: class:parrot_tools.excel.ExcelArgs
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Arguments schema for Excel/ODS Document generation.
relates_to:
- concept: class:parrot_tools.document.DocumentGenerationArgs
  rel: extends
---

# ExcelArgs

Defined in [`parrot_tools.excel`](../summaries/mod:parrot_tools.excel.md).

```python
class ExcelArgs(DocumentGenerationArgs)
```

Arguments schema for Excel/ODS Document generation.

## Methods

- `def validate_content(cls, v)`
- `def validate_sheet_name(cls, v)`
