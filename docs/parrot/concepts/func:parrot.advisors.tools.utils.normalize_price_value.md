---
type: Concept
title: normalize_price_value()
id: func:parrot.advisors.tools.utils.normalize_price_value
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Normalize price string to a float value.
---

# normalize_price_value

```python
def normalize_price_value(price_str: str) -> float
```

Normalize price string to a float value.

Handles:
- K/k notation: "5K" → 5000, "2.5k" → 2500
- M/m notation: "1M" → 1000000
- Commas: "5,000" → 5000
- Dollar signs: "$5000" → 5000
