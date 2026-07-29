---
type: Wiki Summary
title: parrot_tools.breakeven
id: mod:parrot_tools.breakeven
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: BreakEvenAnalysisTool — threshold and root-finding analysis.
relates_to:
- concept: class:parrot_tools.breakeven.BreakEvenAnalysisTool
  rel: defines
- concept: class:parrot_tools.breakeven.BreakEvenInput
  rel: defines
- concept: mod:parrot_tools.abstract
  rel: references
- concept: mod:parrot_tools.whatif
  rel: references
---

# `parrot_tools.breakeven`

BreakEvenAnalysisTool — threshold and root-finding analysis.

Finds the variable value where a target metric reaches a specified threshold.
Uses scipy.optimize.brentq for root finding.

## Classes

- **`BreakEvenInput(BaseModel)`** — Input schema for BreakEvenAnalysisTool.
- **`BreakEvenAnalysisTool(AbstractTool)`** — Find threshold values for target metrics.
