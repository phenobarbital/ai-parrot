---
type: Concept
title: infer_criteria_from_response()
id: func:parrot.advisors.tools.utils.infer_criteria_from_response
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Try to infer criteria from a free-form response.
---

# infer_criteria_from_response

```python
def infer_criteria_from_response(response: str) -> Dict[str, Any]
```

Try to infer criteria from a free-form response.

Handles common patterns like:
- "about 10x12 feet" → max_footprint: 120
- "under $2000" → max_price: 2000
- "no more than 5K" → max_price: 5000
- "for storage" → use_case: storage
