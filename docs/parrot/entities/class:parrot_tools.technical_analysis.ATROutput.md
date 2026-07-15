---
type: Wiki Entity
title: ATROutput
id: class:parrot_tools.technical_analysis.ATROutput
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: ATR (Average True Range) indicator output with stop-loss levels.
---

# ATROutput

Defined in [`parrot_tools.technical_analysis`](../summaries/mod:parrot_tools.technical_analysis.md).

```python
class ATROutput(BaseModel)
```

ATR (Average True Range) indicator output with stop-loss levels.

ATR measures volatility in price terms. Used for:
- Volatility-adjusted stop-loss placement
- Position sizing
- Risk management

Stop-loss levels are provided for both long and short positions.
