---
type: Concept
title: upsert_user_agent_toolkit()
id: func:parrot.auth.oauth2.persistence.upsert_user_agent_toolkit
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Upsert an enablement record in ``user_agent_toolkits``.
---

# upsert_user_agent_toolkit

```python
async def upsert_user_agent_toolkit(row: UserAgentToolkitRow) -> None
```

Upsert an enablement record in ``user_agent_toolkits``.

The composite key is ``(user_id, agent_id, toolkit_id)``.  Calling this
twice is idempotent — only ``enabled_at`` and ``provider`` are updated on
a second call.

Args:
    row: The enablement record to persist.
