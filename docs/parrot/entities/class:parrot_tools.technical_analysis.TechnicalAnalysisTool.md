---
type: Wiki Entity
title: TechnicalAnalysisTool
id: class:parrot_tools.technical_analysis.TechnicalAnalysisTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tool for performing Technical Analysis on stocks and crypto.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# TechnicalAnalysisTool

Defined in [`parrot_tools.technical_analysis`](../summaries/mod:parrot_tools.technical_analysis.md).

```python
class TechnicalAnalysisTool(AbstractToolkit)
```

Tool for performing Technical Analysis on stocks and crypto.
Calculates SMA, RSI, MACD, Bollinger Bands from OHLCV data fetched via other toolkits.

## Methods

- `async def multi_timeframe_analysis(self, symbol: str, ohlcv_daily: pd.DataFrame, ohlcv_weekly: pd.DataFrame | None=None, ohlcv_hourly: pd.DataFrame | None=None) -> Dict[str, Any]` — Compute indicators and scores on each available timeframe,
