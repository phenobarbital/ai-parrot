---
type: Wiki Entity
title: CompositeScore
id: class:parrot_tools.technical_analysis.CompositeScore
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Composite technical score for asset ranking.
---

# CompositeScore

Defined in [`parrot_tools.technical_analysis`](../summaries/mod:parrot_tools.technical_analysis.md).

```python
class CompositeScore(BaseModel)
```

Composite technical score for asset ranking.

Provides a 0-10 bullish/bearish score combining multiple indicators:
- SMA Position (0-2 pts)
- RSI Zone (0-1 pt)
- MACD (0-1.5 pts)
- ADX Trend (0-1.5 pts)
- Momentum (0-2 pts)
- Volume (0-1 pt)
- EMA Alignment (0-1 pt)
