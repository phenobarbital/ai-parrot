---
type: Wiki Entity
title: DfToHtmlTool
id: class:parrot_tools.dftohtml.DfToHtmlTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Tool for converting pandas DataFrames to styled HTML tables.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# DfToHtmlTool

Defined in [`parrot_tools.dftohtml`](../summaries/mod:parrot_tools.dftohtml.md).

```python
class DfToHtmlTool(AbstractTool)
```

Tool for converting pandas DataFrames to styled HTML tables.

This tool takes a pandas DataFrame and converts it to a well-formatted HTML table
with optional CSS styling, Bootstrap integration, and file saving capabilities.
