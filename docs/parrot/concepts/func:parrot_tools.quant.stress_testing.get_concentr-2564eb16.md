---
type: Concept
title: get_concentrated_risk_positions()
id: func:parrot_tools.quant.stress_testing.get_concentrated_risk_positions
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Identify positions that contribute disproportionately to losses.
---

# get_concentrated_risk_positions

```python
def get_concentrated_risk_positions(stress_result: dict, threshold_pct: float=0.1) -> list[dict]
```

Identify positions that contribute disproportionately to losses.

Args:
    stress_result: Output from stress_test_portfolio().
    threshold_pct: Loss threshold as fraction of portfolio (default 10%).

Returns:
    List of positions with high stress impact:
    [{"symbol": "BTC", "scenario": "covid_crash_2020", "loss_pct": -0.15}, ...]
