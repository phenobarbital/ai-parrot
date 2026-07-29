---
type: Wiki Entity
title: MSALCacheTokenCredential
id: class:parrot.interfaces.o365.MSALCacheTokenCredential
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: TokenCredential that uses an MSAL client application with a serialized cache.
---

# MSALCacheTokenCredential

Defined in [`parrot.interfaces.o365`](../summaries/mod:parrot.interfaces.o365.md).

```python
class MSALCacheTokenCredential(TokenCredential)
```

TokenCredential that uses an MSAL client application with a serialized cache.

## Methods

- `def get_token(self, *scopes, **kwargs) -> AccessToken`
