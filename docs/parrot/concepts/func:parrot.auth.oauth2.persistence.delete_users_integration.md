---
type: Concept
title: delete_users_integration()
id: func:parrot.auth.oauth2.persistence.delete_users_integration
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Hard-delete the credential record for ``(user_id, provider)``.
---

# delete_users_integration

```python
async def delete_users_integration(user_id: str, provider: str) -> None
```

Hard-delete the credential record for ``(user_id, provider)``.

A no-op if the record does not exist.

Args:
    user_id: Navigator user identifier.
    provider: Provider identifier, e.g. ``"jira"``.
