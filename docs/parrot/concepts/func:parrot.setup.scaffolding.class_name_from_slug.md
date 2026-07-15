---
type: Concept
title: class_name_from_slug()
id: func:parrot.setup.scaffolding.class_name_from_slug
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Convert a hyphenated slug to a PascalCase class name.
---

# class_name_from_slug

```python
def class_name_from_slug(slug: str) -> str
```

Convert a hyphenated slug to a PascalCase class name.

Args:
    slug: Hyphenated slug (e.g. ``"my-research-agent"``).

Returns:
    PascalCase class name (e.g. ``"MyResearchAgent"``).

Examples:
    >>> class_name_from_slug("my-research-agent")
    'MyResearchAgent'
    >>> class_name_from_slug("bot")
    'Bot'
