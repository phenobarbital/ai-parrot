---
type: Wiki Entity
title: StatisticalTestsTool
id: class:parrot_tools.statistical_tests.StatisticalTestsTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Run statistical hypothesis tests on dataset groups.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# StatisticalTestsTool

Defined in [`parrot_tools.statistical_tests`](../summaries/mod:parrot_tools.statistical_tests.md).

```python
class StatisticalTestsTool(AbstractTool)
```

Run statistical hypothesis tests on dataset groups.

Supports t-test, ANOVA, chi-square, Mann-Whitney, Kruskal-Wallis,
and normality tests. Returns test statistic, p-value, effect size,
and plain-language interpretation.
