---
type: Wiki Summary
title: parrot.advisors.tools.utils
id: mod:parrot.advisors.tools.utils
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Shared utilities for Product Advisor tools.
relates_to:
- concept: func:parrot.advisors.tools.utils.infer_criteria_from_response
  rel: defines
- concept: func:parrot.advisors.tools.utils.normalize_price_value
  rel: defines
---

# `parrot.advisors.tools.utils`

Shared utilities for Product Advisor tools.

## Functions

- `def normalize_price_value(price_str: str) -> float` — Normalize price string to a float value.
- `def infer_criteria_from_response(response: str) -> Dict[str, Any]` — Try to infer criteria from a free-form response.
