---
type: Wiki Entity
title: RegressionAnalysisTool
id: class:parrot_tools.regression_analysis.RegressionAnalysisTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Model quantitative relationships between variables.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# RegressionAnalysisTool

Defined in [`parrot_tools.regression_analysis`](../summaries/mod:parrot_tools.regression_analysis.md).

```python
class RegressionAnalysisTool(AbstractTool)
```

Model quantitative relationships between variables.

Fits linear, polynomial, or log regression using numpy/scipy.
Returns model equation, coefficients, fit diagnostics, and predictions.
