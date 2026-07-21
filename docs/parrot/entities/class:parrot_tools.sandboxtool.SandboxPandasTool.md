---
type: Wiki Entity
title: SandboxPandasTool
id: class:parrot_tools.sandboxtool.SandboxPandasTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Specialized version for Pandas operations with enhanced data handling.
relates_to:
- concept: class:parrot_tools.sandboxtool.SandboxTool
  rel: extends
---

# SandboxPandasTool

Defined in [`parrot_tools.sandboxtool`](../summaries/mod:parrot_tools.sandboxtool.md).

```python
class SandboxPandasTool(SandboxTool)
```

Specialized version for Pandas operations with enhanced data handling.
Drop-in replacement for PythonPandasTool with security.

## Methods

- `async def analyze_dataframe(self, df_name: str, analysis_type: str='summary') -> ToolResult` — Perform automated DataFrame analysis.
