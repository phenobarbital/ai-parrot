---
type: Concept
title: detect_correlation_regimes()
id: func:parrot_tools.quant.correlation.detect_correlation_regimes
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Compare short-term vs long-term correlations to detect regime changes.
---

# detect_correlation_regimes

```python
def detect_correlation_regimes(price_data: dict[str, list[float]], short_window: int=20, long_window: int=120, z_threshold: float=2.0) -> dict
```

Compare short-term vs long-term correlations to detect regime changes.

This directly serves the risk crew instruction:
"Flag when correlations deviate >2 std from historical norm"

Args:
    price_data: Dictionary of {symbol: [prices]}.
    short_window: Recent window for short-term correlation.
    long_window: Historical window for long-term baseline.
    z_threshold: Standard deviation threshold for alerts.

Returns:
    Dictionary with:
    - regime_alerts: List of {pair, short_corr, long_corr, z_score, alert}
    - correlation_matrix_short: Short-term correlation matrix
    - correlation_matrix_long: Long-term correlation matrix

Raises:
    ValueError: If insufficient data points.
