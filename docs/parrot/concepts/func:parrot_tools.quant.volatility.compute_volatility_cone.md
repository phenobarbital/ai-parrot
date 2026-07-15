---
type: Concept
title: compute_volatility_cone()
id: func:parrot_tools.quant.volatility.compute_volatility_cone
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Compute percentile ranks of current volatility across multiple windows.
---

# compute_volatility_cone

```python
def compute_volatility_cone(returns: list[float], windows: list[int] | None=None, annualization: int=252) -> dict
```

Compute percentile ranks of current volatility across multiple windows.

Answers: "Is current 20-day vol high or low relative to history?"

Args:
    returns: Daily return series.
    windows: List of window sizes to analyze. Default: [10, 20, 30, 60, 90, 120].
    annualization: Annualization factor.

Returns:
    Dictionary with structure:
    {
        window: {
            "current": float,
            "percentile": float (0-100),
            "min": float,
            "max": float,
            "median": float,
        }
    }
