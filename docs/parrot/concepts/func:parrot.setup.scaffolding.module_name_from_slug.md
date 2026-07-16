---
type: Concept
title: module_name_from_slug()
id: func:parrot.setup.scaffolding.module_name_from_slug
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Convert a hyphenated slug to a valid Python module name.
---

# module_name_from_slug

```python
def module_name_from_slug(slug: str) -> str
```

Convert a hyphenated slug to a valid Python module name.

Args:
    slug: Hyphenated slug (e.g. ``"my-research-agent"``).

Returns:
    Underscored module name (e.g. ``"my_research_agent"``).
