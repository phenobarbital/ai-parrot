---
type: Wiki Summary
title: parrot_tools.whatif_toolkit
id: mod:parrot_tools.whatif_toolkit
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: WhatIf Toolkit — Decomposed What-If Scenario Analysis.
relates_to:
- concept: class:parrot_tools.whatif_toolkit.AddActionsInput
  rel: defines
- concept: class:parrot_tools.whatif_toolkit.CompareScenariosInput
  rel: defines
- concept: class:parrot_tools.whatif_toolkit.DescribeScenarioInput
  rel: defines
- concept: class:parrot_tools.whatif_toolkit.QuickImpactInput
  rel: defines
- concept: class:parrot_tools.whatif_toolkit.ScenarioState
  rel: defines
- concept: class:parrot_tools.whatif_toolkit.SetConstraintsInput
  rel: defines
- concept: class:parrot_tools.whatif_toolkit.SimulateInput
  rel: defines
- concept: class:parrot_tools.whatif_toolkit.WhatIfToolkit
  rel: defines
- concept: func:parrot_tools.whatif_toolkit.integrate_whatif_toolkit
  rel: defines
- concept: mod:parrot_tools.toolkit
  rel: references
- concept: mod:parrot_tools.whatif
  rel: references
---

# `parrot_tools.whatif_toolkit`

WhatIf Toolkit — Decomposed What-If Scenario Analysis.

Provides 6 focused tools for incremental scenario building:
  1. describe_scenario — create & validate a scenario
  2. add_actions — add possible actions to a scenario
  3. set_constraints — set optimization objectives/constraints
  4. simulate — execute the scenario via WhatIfDSL
  5. quick_impact — fast-path for simple single-action queries
  6. compare_scenarios — side-by-side comparison of solved scenarios

## Classes

- **`ScenarioState`** — Internal state for a scenario being built incrementally.
- **`DescribeScenarioInput(BaseModel)`** — Input for describe_scenario tool.
- **`AddActionsInput(BaseModel)`** — Input for add_actions tool.
- **`SetConstraintsInput(BaseModel)`** — Input for set_constraints tool.
- **`SimulateInput(BaseModel)`** — Input for simulate tool.
- **`QuickImpactInput(BaseModel)`** — Input for quick_impact tool -- the simple fast-path.
- **`CompareScenariosInput(BaseModel)`** — Input for compare_scenarios tool.
- **`WhatIfToolkit(AbstractToolkit)`** — What-If scenario analysis toolkit for simulating hypothetical changes on datasets.

## Functions

- `def integrate_whatif_toolkit(agent, dataset_manager: Optional[Any]=None, pandas_tool: Optional[Any]=None) -> WhatIfToolkit` — Integrate WhatIfToolkit into an agent.
