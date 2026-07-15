---
type: Wiki Entity
title: O365TokenSet
id: class:parrot.auth.o365_oauth.O365TokenSet
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Office 365 token set extension.
relates_to:
- concept: class:parrot.auth.oauth2_base.AbstractOAuth2TokenSet
  rel: extends
---

# O365TokenSet

Defined in [`parrot.auth.o365_oauth`](../summaries/mod:parrot.auth.o365_oauth.md).

```python
class O365TokenSet(AbstractOAuth2TokenSet)
```

Office 365 token set extension.

Adds Microsoft Graph identity fields populated from ``/me``.
