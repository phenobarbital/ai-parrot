---
type: Concept
title: batch_piotroski_scores()
id: func:parrot_tools.quant.piotroski.batch_piotroski_scores
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Calculate F-Scores for multiple symbols.
---

# batch_piotroski_scores

```python
def batch_piotroski_scores(symbols_data: dict[str, PiotroskiInput]) -> dict[str, dict]
```

Calculate F-Scores for multiple symbols.

Args:
    symbols_data: Dictionary of {symbol: PiotroskiInput}.

Returns:
    Dictionary of {symbol: score_result}.
