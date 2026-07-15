---
type: Concept
title: compute_realized_volatility()
id: func:parrot_tools.quant.volatility.compute_realized_volatility
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Compute rolling realized volatility.
---

# compute_realized_volatility

```python
def compute_realized_volatility(returns: list[float], window: int=20, annualization: int=252, method: Literal['close_to_close', 'parkinson', 'garman_klass']='close_to_close', ohlc_data: dict[str, list[float]] | None=None) -> list[float]
```

Compute rolling realized volatility.

Methods:
- close_to_close: Standard deviation of returns (most common)
- parkinson: Uses high-low range, ~5x more efficient than close-to-close
- garman_klass: Uses OHLC, most efficient estimator

Args:
    returns: Daily return series (for close_to_close method).
    window: Rolling window size.
    annualization: 252 for stocks, 365 for crypto.
    method: Volatility estimator method.
    ohlc_data: Required for parkinson/garman_klass.
        Format: {"high": [], "low": [], "open": [], "close": []}

Returns:
    List of rolling annualized volatility values.

Raises:
    ValueError: If method requires ohlc_data but not provided.
