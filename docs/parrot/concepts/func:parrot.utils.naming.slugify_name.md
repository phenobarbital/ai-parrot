---
type: Concept
title: slugify_name()
id: func:parrot.utils.naming.slugify_name
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Convert a user-provided name into a URL-safe slug.
---

# slugify_name

```python
def slugify_name(name: str) -> str
```

Convert a user-provided name into a URL-safe slug.

Strips whitespace, lowercases, replaces non-alphanumeric characters
with hyphens, collapses consecutive hyphens, and strips leading/trailing
hyphens.

Args:
    name: The raw name string from user input.

Returns:
    A lowercase, hyphen-separated slug (e.g. ``"my-cool-bot"``).

Raises:
    ValueError: If the result is empty after normalization.
