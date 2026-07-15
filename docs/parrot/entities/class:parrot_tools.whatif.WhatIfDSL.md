---
type: Wiki Entity
title: WhatIfDSL
id: class:parrot_tools.whatif.WhatIfDSL
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Domain Specific Language for What-If analysis with optimization
---

# WhatIfDSL

Defined in [`parrot_tools.whatif`](../summaries/mod:parrot_tools.whatif.md).

```python
class WhatIfDSL
```

Domain Specific Language for What-If analysis with optimization

## Methods

- `def register_derived_metric(self, name: str, formula: str, description: str='')` — Register a derived metric
- `def initialize_optimizer(self)` — Initialize optimizer after registering metrics
- `def minimize(self, metric: str, weight: float=1.0) -> 'WhatIfDSL'` — Minimize a metric
- `def maximize(self, metric: str, weight: float=1.0) -> 'WhatIfDSL'` — Maximize a metric
- `def target(self, metric: str, value: float, weight: float=1.0) -> 'WhatIfDSL'` — Reach a target value
- `def constrain_change(self, metric: str, max_pct: float) -> 'WhatIfDSL'` — Constraint: metric cannot change more than X%
- `def constrain_min(self, metric: str, min_value: float) -> 'WhatIfDSL'` — Constraint: metric must stay above X
- `def constrain_max(self, metric: str, max_value: float) -> 'WhatIfDSL'` — Constraint: metric must stay below X
- `def constrain_ratio(self, metric: str, reference: str, max_ratio: float) -> 'WhatIfDSL'` — Constraint: ratio between two metrics
- `def can_close_regions(self, regions: Optional[List[str]]=None) -> 'WhatIfDSL'` — Define that regions can be closed
- `def can_exclude_values(self, column: str, values: Optional[List[str]]=None) -> 'WhatIfDSL'` — Define that specific values can be excluded from a column (generic version of can_close_regions)
- `def can_adjust_metric(self, metric: str, min_pct: float=-50, max_pct: float=50, group_by: Optional[str]=None) -> 'WhatIfDSL'` — Define that a metric can be adjusted.
- `def can_scale_proportional(self, base_column: str, affected_columns: List[str], min_pct: float=-50, max_pct: float=100, group_by: Optional[str]=None) -> 'WhatIfDSL'` — Allow scaling a base metric and adjust others proportionally.
- `def can_scale_entity(self, entity_column: str, target_columns: List[str], entities: Optional[List[str]]=None, min_pct: float=-100, max_pct: float=100) -> 'WhatIfDSL'` — Allow scaling specific entities (rows) by a percentage.
- `def solve(self, max_actions: int=5, algorithm: str='greedy') -> ScenarioResult` — Find best combination of actions that meets constraints.
