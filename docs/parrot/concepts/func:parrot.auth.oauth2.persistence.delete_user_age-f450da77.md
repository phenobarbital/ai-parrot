---
type: Concept
title: delete_user_agent_toolkits_by_provider()
id: func:parrot.auth.oauth2.persistence.delete_user_agent_toolkits_by_provider
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Cascade-delete all enablement records for ``(user_id, provider)``.
---

# delete_user_agent_toolkits_by_provider

```python
async def delete_user_agent_toolkits_by_provider(user_id: str, provider: str) -> None
```

Cascade-delete all enablement records for ``(user_id, provider)``.

This implements the disconnect cascade rule: disconnecting a provider
removes ALL ``user_agent_toolkits`` rows for that user+provider regardless
of ``agent_id``.  A no-op when no rows exist.

Args:
    user_id: Navigator user identifier.
    provider: Provider identifier, e.g. ``"jira"``.
