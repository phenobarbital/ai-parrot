---
type: Wiki Entity
title: CalculatorTool
id: class:parrot_tools.calculator.tool.CalculatorTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Advanced calculator tool with dynamically loaded operations.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# CalculatorTool

Defined in [`parrot_tools.calculator.tool`](../summaries/mod:parrot_tools.calculator.tool.md).

```python
class CalculatorTool(AbstractTool)
```

Advanced calculator tool with dynamically loaded operations.

Supports mathematical, statistical, and scientific computations
by loading operation functions from the operations/ folder.

## Methods

- `def list_operations(self) -> List[str]` — List all available operations.
