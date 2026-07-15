---
type: Concept
title: rank_by_fscore()
id: func:parrot_tools.quant.piotroski.rank_by_fscore
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Rank symbols by F-Score descending.
---

# rank_by_fscore

```python
def rank_by_fscore(symbols_data: dict[str, PiotroskiInput]) -> list[tuple[str, int, str]]
```

Rank symbols by F-Score descending.

Args:
    symbols_data: Dictionary of {symbol: PiotroskiInput}.

Returns:
    List of (symbol, score, interpretation) tuples, sorted by score descending.
