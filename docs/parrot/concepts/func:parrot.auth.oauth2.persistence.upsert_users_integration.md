---
type: Concept
title: upsert_users_integration()
id: func:parrot.auth.oauth2.persistence.upsert_users_integration
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Upsert a credential record in ``users_integrations``.
---

# upsert_users_integration

```python
async def upsert_users_integration(row: UsersIntegrationRow) -> None
```

Upsert a credential record in ``users_integrations``.

The composite key is ``(user_id, provider)``.  A second call with the
same key performs last-write-wins update of all other fields.

Args:
    row: The credential record to persist.
