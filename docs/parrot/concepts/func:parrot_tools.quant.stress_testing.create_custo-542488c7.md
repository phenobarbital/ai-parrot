---
type: Concept
title: create_custom_scenario()
id: func:parrot_tools.quant.stress_testing.create_custom_scenario
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Create a custom stress scenario.
---

# create_custom_scenario

```python
def create_custom_scenario(name: str, asset_shocks: dict[str, float], description: str | None=None) -> StressScenario
```

Create a custom stress scenario.

Args:
    name: Scenario name.
    asset_shocks: {symbol: shock_pct} mapping (e.g., -0.20 = -20%).
    description: Optional description.

Returns:
    StressScenario object.
