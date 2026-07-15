---
type: Concept
title: classify_term_structure()
id: func:parrot_tools.quant.volatility.classify_term_structure
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Classify volatility term structure shape.
---

# classify_term_structure

```python
def classify_term_structure(term_structure: dict) -> str
```

Classify volatility term structure shape.

Args:
    term_structure: Result from compute_volatility_term_structure.

Returns:
    "contango" (normal), "backwardation" (inverted), or "flat".
