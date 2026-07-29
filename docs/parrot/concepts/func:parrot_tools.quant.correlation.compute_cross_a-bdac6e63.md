---
type: Concept
title: compute_cross_asset_correlation()
id: func:parrot_tools.quant.correlation.compute_cross_asset_correlation
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Compute correlation between equities (252 trading days) and crypto (365 days).
---

# compute_cross_asset_correlation

```python
def compute_cross_asset_correlation(equity_prices: dict[str, list[float]], crypto_prices: dict[str, list[float]], timestamps_equity: list[str], timestamps_crypto: list[str], alignment: str='daily_close') -> dict
```

Compute correlation between equities (252 trading days) and crypto (365 days).

Aligns on common dates before computing correlation.

Args:
    equity_prices: Dictionary of {symbol: [prices]} for equities.
    crypto_prices: Dictionary of {symbol: [prices]} for crypto.
    timestamps_equity: List of date strings for equity prices.
    timestamps_crypto: List of date strings for crypto prices.
    alignment: Alignment method (currently only 'daily_close' supported).

Returns:
    Dictionary with:
    - cross_asset_correlations: {pair: correlation}
    - full_matrix: Complete correlation matrix
    - common_dates_count: Number of overlapping dates
    - alignment: Alignment method used

Raises:
    ValueError: If insufficient overlapping dates.
