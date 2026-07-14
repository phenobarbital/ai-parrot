---
type: Concept
title: slugify()
id: func:parrot.setup.scaffolding.slugify
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Convert a human-readable name to a URL-safe hyphenated slug.
---

# slugify

```python
def slugify(name: str) -> str
```

Convert a human-readable name to a URL-safe hyphenated slug.

Strips special characters, collapses whitespace to hyphens, and
lower-cases the result.

Args:
    name: Human-readable string (e.g. ``"My Research Agent #1"``).

Returns:
    Lowercase hyphenated slug (e.g. ``"my-research-agent-1"``).

Examples:
    >>> slugify("My Agent")
    'my-agent'
    >>> slugify("Agent #1 (Test)")
    'agent-1-test'
