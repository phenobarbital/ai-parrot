---
type: Wiki Entity
title: CollaborativeConfig
id: class:parrot.integrations.matrix.crew.config.CollaborativeConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configuration for collaborative multi-agent investigation sessions.
---

# CollaborativeConfig

Defined in [`parrot.integrations.matrix.crew.config`](../summaries/mod:parrot.integrations.matrix.crew.config.md).

```python
class CollaborativeConfig(BaseModel)
```

Configuration for collaborative multi-agent investigation sessions.

Controls how ``!investigate`` commands trigger collaborative sessions,
including round counts, timeouts, summarizer agent, and verbosity.

Attributes:
    command_prefix: Trigger command that initiates a collaborative session.
    max_rounds: Number of cross-pollination rounds (1-10).
    agent_timeout: Per-agent response timeout in seconds.
    session_timeout: Maximum total session duration in seconds.
    summarizer_agent: Agent name for final synthesis (None = post raw results).
    session_verbosity: 'full' posts all announcements, 'minimal' reduces them.
    include_chat_context: Pass recent chat history to the summarizer.
