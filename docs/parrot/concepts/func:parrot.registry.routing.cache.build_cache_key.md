---
type: Concept
title: build_cache_key()
id: func:parrot.registry.routing.cache.build_cache_key
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Build a stable, compact cache key.
---

# build_cache_key

```python
def build_cache_key(query: str, store_fingerprint: tuple[str, ...]) -> str
```

Build a stable, compact cache key.

Normalisation: lowercase + collapse whitespace + strip leading/trailing
whitespace.  The sorted *store_fingerprint* tuple is included so that a
change in available stores invalidates stale decisions.

Args:
    query: Raw user query string.
    store_fingerprint: Sorted tuple of store-type strings (or other stable
        identifiers) that uniquely identifies the current store
        configuration.

Returns:
    A 40-character hex string (SHA-1).
