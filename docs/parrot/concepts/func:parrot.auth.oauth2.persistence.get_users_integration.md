---
type: Concept
title: get_users_integration()
id: func:parrot.auth.oauth2.persistence.get_users_integration
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Fetch a single credential record by ``(user_id, provider)``.
---

# get_users_integration

```python
async def get_users_integration(user_id: str, provider: str) -> Optional[UsersIntegrationRow]
```

Fetch a single credential record by ``(user_id, provider)``.

Args:
    user_id: Navigator user identifier.
    provider: Provider identifier, e.g. ``"jira"``.

Returns:
    The :class:`~parrot.integrations.oauth2.models.UsersIntegrationRow`
    if found, otherwise ``None``.
