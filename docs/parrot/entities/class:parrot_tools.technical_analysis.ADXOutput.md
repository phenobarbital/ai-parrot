---
type: Wiki Entity
title: ADXOutput
id: class:parrot_tools.technical_analysis.ADXOutput
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: ADX (Average Directional Index) indicator output.
---

# ADXOutput

Defined in [`parrot_tools.technical_analysis`](../summaries/mod:parrot_tools.technical_analysis.md).

```python
class ADXOutput(BaseModel)
```

ADX (Average Directional Index) indicator output.

ADX measures trend strength regardless of direction.
- ADX < 20: absent (no trend)
- ADX 20-25: weak trend
- ADX 25-50: strong trend
- ADX > 50: extreme trend

+DI > -DI indicates bullish direction; -DI > +DI indicates bearish.
