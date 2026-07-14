---
type: Wiki Summary
title: parrot_tools.quant.volatility
id: mod:parrot_tools.quant.volatility
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Volatility Analytics for QuantToolkit.
relates_to:
- concept: func:parrot_tools.quant.volatility.classify_term_structure
  rel: defines
- concept: func:parrot_tools.quant.volatility.compute_iv_rv_spread
  rel: defines
- concept: func:parrot_tools.quant.volatility.compute_realized_volatility
  rel: defines
- concept: func:parrot_tools.quant.volatility.compute_volatility_cone
  rel: defines
- concept: func:parrot_tools.quant.volatility.compute_volatility_single
  rel: defines
- concept: func:parrot_tools.quant.volatility.compute_volatility_term_structure
  rel: defines
- concept: func:parrot_tools.quant.volatility.interpret_iv_rv_spread
  rel: defines
- concept: func:parrot_tools.quant.volatility.interpret_volatility_cone
  rel: defines
---

# `parrot_tools.quant.volatility`

Volatility Analytics for QuantToolkit.

Provides volatility analysis for sentiment and risk monitoring:
- Realized volatility estimators (close-to-close, Parkinson, Garman-Klass)
- Volatility cone analysis (percentile ranks across windows)
- IV vs RV spread analysis with regime classification

Volatility Estimator Comparison:
- Close-to-Close: Most common, uses return standard deviation
- Parkinson (1980): Uses high-low range, ~5x more efficient
- Garman-Klass (1980): Uses OHLC, most efficient estimator

## Functions

- `def compute_realized_volatility(returns: list[float], window: int=20, annualization: int=252, method: Literal['close_to_close', 'parkinson', 'garman_klass']='close_to_close', ohlc_data: dict[str, list[float]] | None=None) -> list[float]` — Compute rolling realized volatility.
- `def compute_volatility_single(returns: list[float], annualization: int=252) -> float` — Compute single volatility value from returns.
- `def compute_volatility_cone(returns: list[float], windows: list[int] | None=None, annualization: int=252) -> dict` — Compute percentile ranks of current volatility across multiple windows.
- `def interpret_volatility_cone(cone_result: dict) -> str` — Interpret volatility cone results.
- `def compute_iv_rv_spread(implied_vol: float, realized_vol_series: list[float], window: int=20) -> dict` — Compute IV vs RV spread and classify the regime.
- `def interpret_iv_rv_spread(spread_result: dict) -> str` — Interpret IV/RV spread results.
- `def compute_volatility_term_structure(returns: list[float], windows: list[int] | None=None, annualization: int=252) -> dict` — Compute volatility across different time horizons.
- `def classify_term_structure(term_structure: dict) -> str` — Classify volatility term structure shape.
