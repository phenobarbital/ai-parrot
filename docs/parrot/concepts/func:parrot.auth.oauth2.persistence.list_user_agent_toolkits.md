---
type: Concept
title: list_user_agent_toolkits()
id: func:parrot.auth.oauth2.persistence.list_user_agent_toolkits
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return all enablement records for a ``(user_id, agent_id)`` pair.
---

# list_user_agent_toolkits

```python
async def list_user_agent_toolkits(user_id: str, agent_id: str) -> List[UserAgentToolkitRow]
```

Return all enablement records for a ``(user_id, agent_id)`` pair.

Args:
    user_id: Navigator user identifier.
    agent_id: Agent identifier.

Returns:
    List of :class:`~parrot.integrations.oauth2.models.UserAgentToolkitRow`
    instances.  Empty list when none are found.
