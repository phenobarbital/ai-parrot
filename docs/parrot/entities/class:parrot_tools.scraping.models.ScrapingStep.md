---
type: Wiki Entity
title: ScrapingStep
id: class:parrot_tools.scraping.models.ScrapingStep
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: ScrapingStep that wraps a BrowserAction.
---

# ScrapingStep

Defined in [`parrot_tools.scraping.models`](../summaries/mod:parrot_tools.scraping.models.md).

```python
class ScrapingStep
```

ScrapingStep that wraps a BrowserAction.

Used to define a step in a scraping sequence.

Example:
    {
        'action': 'navigate',
        'target': 'https://www.consumeraffairs.com/homeowners/service-protection-advantage.html',
        'description': 'Consumer Affairs home'
    },

## Methods

- `def to_dict(self) -> Dict[str, Any]` — Convert to dictionary for serialization
- `def from_dict(cls, data: Dict[str, Any]) -> 'ScrapingStep'` — Create ScrapingStep from dictionary
