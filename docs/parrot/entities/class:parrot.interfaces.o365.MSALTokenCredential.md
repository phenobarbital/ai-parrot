---
type: Wiki Entity
title: MSALTokenCredential
id: class:parrot.interfaces.o365.MSALTokenCredential
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Custom TokenCredential that uses MSAL tokens for azure-identity compatibility.
---

# MSALTokenCredential

Defined in [`parrot.interfaces.o365`](../summaries/mod:parrot.interfaces.o365.md).

```python
class MSALTokenCredential(TokenCredential)
```

Custom TokenCredential that uses MSAL tokens for azure-identity compatibility.
This allows us to use MSAL-acquired tokens with the Graph SDK.

## Methods

- `def get_token(self, *scopes, **kwargs) -> AccessToken` — Get token using MSAL.
