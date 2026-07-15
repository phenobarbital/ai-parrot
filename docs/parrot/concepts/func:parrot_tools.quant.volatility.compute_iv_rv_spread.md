---
type: Concept
title: compute_iv_rv_spread()
id: func:parrot_tools.quant.volatility.compute_iv_rv_spread
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Compute IV vs RV spread and classify the regime.
---

# compute_iv_rv_spread

```python
def compute_iv_rv_spread(implied_vol: float, realized_vol_series: list[float], window: int=20) -> dict
```

Compute IV vs RV spread and classify the regime.

- IV >> RV: Fear premium is elevated (contrarian buy signal)
- IV << RV: Complacency (contrarian sell signal)
- IV ≈ RV: Normal regime

Args:
    implied_vol: Current implied volatility (annualized, from options).
    realized_vol_series: Historical realized vol series.
    window: Window for current RV calculation.

Returns:
    Dictionary with:
    - implied_vol: float
    - realized_vol: float
    - spread: float (IV - RV)
    - spread_pct: float ((IV - RV) / RV * 100)
    - percentile: float (where current spread falls historically)
    - regime: "fear_premium" | "complacent" | "normal"
