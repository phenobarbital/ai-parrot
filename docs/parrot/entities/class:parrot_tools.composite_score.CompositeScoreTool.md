---
type: Wiki Entity
title: CompositeScoreTool
id: class:parrot_tools.composite_score.CompositeScoreTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tool for computing composite technical scores for asset ranking.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# CompositeScoreTool

Defined in [`parrot_tools.composite_score`](../summaries/mod:parrot_tools.composite_score.md).

```python
class CompositeScoreTool(AbstractToolkit)
```

Tool for computing composite technical scores for asset ranking.

Enables queries like "which of these 10 stocks has the strongest bullish setup?"
and powers the equity research crew's scanning capabilities.

Score Components (max 10 points):
- SMA Position: 0-2 pts (price relative to SMA50/SMA200)
- RSI Zone: 0-1 pt (momentum zone scoring)
- MACD: 0-1.5 pts (trend confirmation)
- ADX Trend: 0-1.5 pts (trend strength)
- Momentum: 0-2 pts (price momentum)
- Volume: 0-1 pt (volume confirmation)
- EMA Alignment: 0-1 pt (EMA stack alignment)

## Methods

- `def tech_tool(self) -> TechnicalAnalysisTool` — Lazy initialization of TechnicalAnalysisTool.
- `async def compute_score(self, symbol: str, asset_type: Literal['stock', 'crypto']='stock', score_type: Literal['bullish', 'bearish']='bullish', source: str='alpaca', lookback_days: int=365) -> CompositeScore` — Public async method for computing composite score.
