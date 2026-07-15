---
type: Wiki Entity
title: MatrixCrewAgentEntry
id: class:parrot.integrations.matrix.crew.config.MatrixCrewAgentEntry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for a single agent in the Matrix crew.
---

# MatrixCrewAgentEntry

Defined in [`parrot.integrations.matrix.crew.config`](../summaries/mod:parrot.integrations.matrix.crew.config.md).

```python
class MatrixCrewAgentEntry(BaseModel)
```

Configuration for a single agent in the Matrix crew.

Attributes:
    chatbot_id: BotManager lookup key.
    display_name: Human-readable name shown in Matrix.
    mxid_localpart: Localpart of the virtual MXID (e.g. "analyst").
    avatar_url: Optional mxc:// URL for the agent's avatar.
    dedicated_room_id: Agent's own private room (optional).
    skills: Skill descriptions shown on the status board.
    tags: Routing tags for message routing.
    file_types: Accepted file MIME types.
