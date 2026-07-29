---
type: Wiki Entity
title: MatrixAgentCard
id: class:parrot.integrations.matrix.crew.registry.MatrixAgentCard
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Agent identity and runtime status for a Matrix crew.
---

# MatrixAgentCard

Defined in [`parrot.integrations.matrix.crew.registry`](../summaries/mod:parrot.integrations.matrix.crew.registry.md).

```python
class MatrixAgentCard(BaseModel)
```

Agent identity and runtime status for a Matrix crew.

Attributes:
    agent_name: Internal agent name (key in the crew config).
    display_name: Human-readable display name shown in Matrix.
    mxid: Full ``@user:server`` Matrix ID.
    status: Current status — one of ``ready``, ``busy``, ``offline``.
    current_task: Short description of the current task (when busy).
    skills: Skill descriptions shown on the status board.
    joined_at: Timestamp when the agent joined the crew.
    last_seen: Timestamp of the last status update.

## Methods

- `def to_status_line(self) -> str` — Render a status line for the pinned status board.
