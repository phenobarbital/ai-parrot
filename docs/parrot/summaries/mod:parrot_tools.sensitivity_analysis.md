---
type: Wiki Summary
title: parrot_tools.sensitivity_analysis
id: mod:parrot_tools.sensitivity_analysis
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: SensitivityAnalysisTool — One-at-a-time sensitivity analysis.
relates_to:
- concept: class:parrot_tools.sensitivity_analysis.SensitivityAnalysisInput
  rel: defines
- concept: class:parrot_tools.sensitivity_analysis.SensitivityAnalysisTool
  rel: defines
- concept: mod:parrot_tools.abstract
  rel: references
- concept: mod:parrot_tools.whatif
  rel: references
---

# `parrot_tools.sensitivity_analysis`

SensitivityAnalysisTool — One-at-a-time sensitivity analysis.

Determines which input variables have the greatest impact on a target metric.
Generates tornado-style rankings and elasticity coefficients.

## Classes

- **`SensitivityAnalysisInput(BaseModel)`** — Input schema for SensitivityAnalysisTool.
- **`SensitivityAnalysisTool(AbstractTool)`** — Analyze which variables have the greatest impact on a target metric.
