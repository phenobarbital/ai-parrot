---
type: Wiki Entity
title: ScrapingPlanTool
id: class:parrot_tools.think.ScrapingPlanTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Specialized thinking tool for web scraping tasks.
relates_to:
- concept: class:parrot_tools.think.ThinkTool
  rel: extends
---

# ScrapingPlanTool

Defined in [`parrot_tools.think`](../summaries/mod:parrot_tools.think.md).

```python
class ScrapingPlanTool(ThinkTool)
```

Specialized thinking tool for web scraping tasks.

Guides the agent to plan scraping strategy considering page structure,
anti-bot measures, and selector reliability.

Example:
    >>> tool = ScrapingPlanTool()
    >>> result = await tool.execute(
    ...     thoughts="Target page uses infinite scroll with lazy loading. "
    ...              "I'll use incremental scrolling with dynamic waits. "
    ...              "Product cards have consistent class 'product-item'."
    ... )
