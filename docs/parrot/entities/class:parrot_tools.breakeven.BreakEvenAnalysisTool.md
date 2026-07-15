---
type: Wiki Entity
title: BreakEvenAnalysisTool
id: class:parrot_tools.breakeven.BreakEvenAnalysisTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Find threshold values for target metrics.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# BreakEvenAnalysisTool

Defined in [`parrot_tools.breakeven`](../summaries/mod:parrot_tools.breakeven.md).

```python
class BreakEvenAnalysisTool(AbstractTool)
```

Find threshold values for target metrics.

Answers 'how many kiosks do we need to cover the cost of 4 new warehouses?'
using root-finding algorithms.
