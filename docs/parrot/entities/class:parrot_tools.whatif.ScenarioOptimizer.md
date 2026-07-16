---
type: Wiki Entity
title: ScenarioOptimizer
id: class:parrot_tools.whatif.ScenarioOptimizer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Optimizer with support for derived metrics
---

# ScenarioOptimizer

Defined in [`parrot_tools.whatif`](../summaries/mod:parrot_tools.whatif.md).

```python
class ScenarioOptimizer
```

Optimizer with support for derived metrics

## Methods

- `def evaluate_scenario(self, df: pd.DataFrame) -> Dict[str, Dict]` — Evaluate metrics of a scenario (including derived)
- `def check_constraints(self, df: pd.DataFrame, constraints: List[Constraint]) -> Tuple[bool, List[str]]` — Check if scenario meets constraints
- `def objective_function(self, df: pd.DataFrame, objectives: List[Objective]) -> float` — Calculate objective function value
