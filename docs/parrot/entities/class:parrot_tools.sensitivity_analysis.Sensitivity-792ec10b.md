---
type: Wiki Entity
title: SensitivityAnalysisTool
id: class:parrot_tools.sensitivity_analysis.SensitivityAnalysisTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Analyze which variables have the greatest impact on a target metric.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# SensitivityAnalysisTool

Defined in [`parrot_tools.sensitivity_analysis`](../summaries/mod:parrot_tools.sensitivity_analysis.md).

```python
class SensitivityAnalysisTool(AbstractTool)
```

Analyze which variables have the greatest impact on a target metric.

Performs one-at-a-time sensitivity analysis: varies each input variable
by +/-N% while holding others constant, measures impact on the target
metric, and ranks variables by absolute impact.
