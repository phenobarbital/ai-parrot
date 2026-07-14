---
type: Wiki Entity
title: UserAgentToolkitRow
id: class:parrot.auth.oauth2.models.UserAgentToolkitRow
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Per-``(user, agent, toolkit)`` enablement record stored in
---

# UserAgentToolkitRow

Defined in [`parrot.auth.oauth2.models`](../summaries/mod:parrot.auth.oauth2.models.md).

```python
class UserAgentToolkitRow(BaseModel)
```

Per-``(user, agent, toolkit)`` enablement record stored in
``user_agent_toolkits``.

The composite key is ``(user_id, agent_id, toolkit_id)``.

Attributes:
    user_id: Navigator user identifier.
    agent_id: Agent identifier (slug or UUID used by the manager).
    toolkit_id: Toolkit identifier — equals ``provider`` for OAuth toolkits.
    provider: Provider identifier, e.g. ``"jira"``.
    enabled_at: When the user enabled this toolkit on this agent.
