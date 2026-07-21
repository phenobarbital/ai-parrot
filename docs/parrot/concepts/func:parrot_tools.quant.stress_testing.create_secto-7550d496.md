---
type: Concept
title: create_sector_rotation_scenario()
id: func:parrot_tools.quant.stress_testing.create_sector_rotation_scenario
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Create a sector rotation scenario.
---

# create_sector_rotation_scenario

```python
def create_sector_rotation_scenario(sector_shocks: dict[str, float], sector_mapping: dict[str, str]) -> StressScenario
```

Create a sector rotation scenario.

Args:
    sector_shocks: {sector: shock_pct} mapping.
        Example: {"tech": -0.15, "energy": 0.10, "utilities": 0.05}
    sector_mapping: {symbol: sector} mapping.
        Example: {"AAPL": "tech", "XOM": "energy", "NEE": "utilities"}

Returns:
    StressScenario with symbol-level shocks derived from sectors.
