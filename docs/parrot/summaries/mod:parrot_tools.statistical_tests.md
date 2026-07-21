---
type: Wiki Summary
title: parrot_tools.statistical_tests
id: mod:parrot_tools.statistical_tests
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: StatisticalTestsTool — t-test, ANOVA, chi-square, normality.
relates_to:
- concept: class:parrot_tools.statistical_tests.StatisticalTestInput
  rel: defines
- concept: class:parrot_tools.statistical_tests.StatisticalTestsTool
  rel: defines
- concept: mod:parrot_tools.abstract
  rel: references
---

# `parrot_tools.statistical_tests`

StatisticalTestsTool — t-test, ANOVA, chi-square, normality.

Validates whether differences between groups or scenarios are
statistically significant.

## Classes

- **`StatisticalTestInput(BaseModel)`** — Input schema for StatisticalTestsTool.
- **`StatisticalTestsTool(AbstractTool)`** — Run statistical hypothesis tests on dataset groups.
