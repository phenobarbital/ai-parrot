---
type: Concept
title: create_volatility_shock_scenario()
id: func:parrot_tools.quant.stress_testing.create_volatility_shock_scenario
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Create a scenario where volatility spikes by a multiplier.
---

# create_volatility_shock_scenario

```python
def create_volatility_shock_scenario(current_volatilities: dict[str, float], multiplier: float=2.0, vol_to_return_factor: float=-0.5) -> StressScenario
```

Create a scenario where volatility spikes by a multiplier.

Higher vol typically correlates with negative returns.
Rule of thumb: 2x vol spike ~ -10% to -20% return for equities.

Args:
    current_volatilities: {symbol: current_annual_vol} mapping.
    multiplier: How much vol increases (2.0 = doubles).
    vol_to_return_factor: Conversion factor (negative = vol up means returns down).

Returns:
    StressScenario with estimated return shocks.

Example:
    >>> current_vols = {"SPY": 0.20, "BTC": 0.60}
    >>> scenario = create_volatility_shock_scenario(current_vols, multiplier=2.0)
    >>> # BTC will have larger shock due to higher base volatility
