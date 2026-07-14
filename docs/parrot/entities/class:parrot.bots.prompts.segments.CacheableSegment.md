---
type: Wiki Entity
title: CacheableSegment
id: class:parrot.bots.prompts.segments.CacheableSegment
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: One chunk of the system prompt with a cache-eligibility flag.
---

# CacheableSegment

Defined in [`parrot.bots.prompts.segments`](../summaries/mod:parrot.bots.prompts.segments.md).

```python
class CacheableSegment
```

One chunk of the system prompt with a cache-eligibility flag.

Attributes:
    text: The rendered text of this segment.
    cacheable: Whether this segment is eligible for provider-side caching.
        CONFIGURE-phase layers produce ``cacheable=True`` segments;
        REQUEST-phase layers produce ``cacheable=False`` segments.
    ttl_hint: Reserved for forward-compatibility. Not translated by any
        provider in v1. Use ``'short'`` or ``'long'`` as hints for future
        TTL-aware caching strategies.
