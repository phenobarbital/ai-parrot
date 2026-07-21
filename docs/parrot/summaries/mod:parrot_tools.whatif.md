---
type: Wiki Summary
title: parrot_tools.whatif
id: mod:parrot_tools.whatif
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: What-If Scenario Analysis Tool for AI-Parrot
relates_to:
- concept: class:parrot_tools.whatif.Action
  rel: defines
- concept: class:parrot_tools.whatif.Constraint
  rel: defines
- concept: class:parrot_tools.whatif.ConstraintType
  rel: defines
- concept: class:parrot_tools.whatif.DerivedMetric
  rel: defines
- concept: class:parrot_tools.whatif.MetricsCalculator
  rel: defines
- concept: class:parrot_tools.whatif.Objective
  rel: defines
- concept: class:parrot_tools.whatif.ObjectiveType
  rel: defines
- concept: class:parrot_tools.whatif.ScenarioOptimizer
  rel: defines
- concept: class:parrot_tools.whatif.ScenarioResult
  rel: defines
- concept: class:parrot_tools.whatif.WhatIfAction
  rel: defines
- concept: class:parrot_tools.whatif.WhatIfConstraint
  rel: defines
- concept: class:parrot_tools.whatif.WhatIfDSL
  rel: defines
- concept: class:parrot_tools.whatif.WhatIfInput
  rel: defines
- concept: class:parrot_tools.whatif.WhatIfObjective
  rel: defines
- concept: class:parrot_tools.whatif.WhatIfTool
  rel: defines
- concept: func:parrot_tools.whatif.integrate_whatif_tool
  rel: defines
- concept: func:parrot_tools.whatif.validate_dict_or_json
  rel: defines
- concept: mod:parrot_tools.abstract
  rel: references
---

# `parrot_tools.whatif`

What-If Scenario Analysis Tool for AI-Parrot
Supports derived metrics, constraints, and optimization

## Classes

- **`ObjectiveType(Enum)`** — Type of optimization objective
- **`ConstraintType(Enum)`** — Type of constraint
- **`Objective`** — Defines an optimization objective
- **`Constraint`** — Defines a constraint
- **`Action`** — Defines a possible action
- **`ScenarioResult`** — Result of an optimized scenario
- **`DerivedMetric(BaseModel)`** — Calculated/derived metric
- **`WhatIfObjective(BaseModel)`** — Objective for scenario optimization
- **`WhatIfConstraint(BaseModel)`** — Constraint for scenario
- **`WhatIfAction(BaseModel)`** — Possible action to take
- **`WhatIfInput(BaseModel)`** — Input schema for WhatIfTool
- **`MetricsCalculator`** — Calculates derived metrics on DataFrames
- **`ScenarioOptimizer`** — Optimizer with support for derived metrics
- **`WhatIfDSL`** — Domain Specific Language for What-If analysis with optimization
- **`WhatIfTool(AbstractTool)`** — What-If Analysis Tool with support for derived metrics and optimization.

## Functions

- `def validate_dict_or_json(v: Any) -> Dict` — Validate that value is a dict, or parse it from JSON string
- `def integrate_whatif_tool(agent) -> WhatIfTool` — Integrate WhatIfTool into an existing PandasAgent.
