---
type: Concept
title: deduplicate_name()
id: func:parrot.utils.naming.deduplicate_name
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Find a unique name by appending a numeric suffix if needed.
---

# deduplicate_name

```python
async def deduplicate_name(slug: str, exists_fn: Callable[[str], Awaitable[Optional[str]]]) -> str
```

Find a unique name by appending a numeric suffix if needed.

Calls *exists_fn* to check whether a candidate name is already taken.
If the base slug is free, it is returned as-is.  Otherwise suffixes
``-2`` through ``-99`` are tried.

Args:
    slug: The base slug to check (output of :func:`slugify_name`).
    exists_fn: An async callable that receives a candidate name and
        returns a non-``None`` value (e.g. ``"database"``) when the
        name is taken, or ``None`` when it is available.

Returns:
    The first available candidate name.

Raises:
    ValueError: If all suffixes up to ``-99`` are exhausted.
