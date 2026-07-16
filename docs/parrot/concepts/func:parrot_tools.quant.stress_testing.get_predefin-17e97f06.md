---
type: Concept
title: get_predefined_scenario()
id: func:parrot_tools.quant.stress_testing.get_predefined_scenario
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Get a predefined stress scenario by name.
---

# get_predefined_scenario

```python
def get_predefined_scenario(name: str) -> StressScenario
```

Get a predefined stress scenario by name.

Args:
    name: Scenario name (e.g., "covid_crash_2020").

Returns:
    StressScenario object.

Raises:
    ValueError: If scenario name is unknown.
