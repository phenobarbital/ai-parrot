---
type: Wiki Entity
title: WhatIfToolkit
id: class:parrot_tools.whatif_toolkit.WhatIfToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: What-If scenario analysis toolkit for simulating hypothetical changes on
  datasets.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# WhatIfToolkit

Defined in [`parrot_tools.whatif_toolkit`](../summaries/mod:parrot_tools.whatif_toolkit.md).

```python
class WhatIfToolkit(AbstractToolkit)
```

What-If scenario analysis toolkit for simulating hypothetical changes on datasets.

## Methods

- `async def describe_scenario(self, df_name: str, scenario_description: str, derived_metrics: Optional[List[DerivedMetric]]=None) -> str` — Create and validate a what-if scenario on a dataset.
- `async def add_actions(self, scenario_id: str, actions: List[WhatIfAction]) -> str` — Add possible actions to an existing scenario.
- `async def set_constraints(self, scenario_id: str, objectives: Optional[List[WhatIfObjective]]=None, constraints: Optional[List[WhatIfConstraint]]=None) -> str` — Define optimization objectives and constraints for a scenario.
- `async def simulate(self, scenario_id: str, algorithm: str='greedy', max_actions: int=5) -> str` — Execute a configured scenario using the WhatIfDSL optimization engine.
- `async def quick_impact(self, df_name: str, action_description: str, action_type: str, target: str, parameters: Optional[Dict[str, Any]]=None) -> str` — Fast-path for simple what-if queries. Resolves dataset, applies a single action,
- `async def compare_scenarios(self, scenario_ids: List[str]) -> str` — Compare two or more simulated scenarios side by side.
