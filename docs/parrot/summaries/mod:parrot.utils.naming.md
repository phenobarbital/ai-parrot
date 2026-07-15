---
type: Wiki Summary
title: parrot.utils.naming
id: mod:parrot.utils.naming
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Name normalization utilities for bot/agent creation.
relates_to:
- concept: func:parrot.utils.naming.deduplicate_name
  rel: defines
- concept: func:parrot.utils.naming.slugify_name
  rel: defines
---

# `parrot.utils.naming`

Name normalization utilities for bot/agent creation.

Provides slug generation and de-duplication for agent names used in
URLs and database identifiers.

## Functions

- `def slugify_name(name: str) -> str` — Convert a user-provided name into a URL-safe slug.
- `async def deduplicate_name(slug: str, exists_fn: Callable[[str], Awaitable[Optional[str]]]) -> str` — Find a unique name by appending a numeric suffix if needed.
