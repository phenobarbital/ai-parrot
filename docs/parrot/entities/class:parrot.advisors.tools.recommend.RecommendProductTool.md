---
type: Wiki Entity
title: RecommendProductTool
id: class:parrot.advisors.tools.recommend.RecommendProductTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Generates a final product recommendation based on collected criteria.
relates_to:
- concept: class:parrot.advisors.tools.base.BaseAdvisorTool
  rel: extends
---

# RecommendProductTool

Defined in [`parrot.advisors.tools.recommend`](../summaries/mod:parrot.advisors.tools.recommend.md).

```python
class RecommendProductTool(BaseAdvisorTool)
```

Generates a final product recommendation based on collected criteria.

This tool:
1. Analyzes remaining products against user criteria
2. Selects the best match
3. Explains why it's recommended
4. Optionally suggests alternatives

Use when the selection is narrowed to 1-3 products.
