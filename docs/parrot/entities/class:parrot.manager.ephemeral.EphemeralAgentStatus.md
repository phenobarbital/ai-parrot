---
type: Wiki Entity
title: EphemeralAgentStatus
id: class:parrot.manager.ephemeral.EphemeralAgentStatus
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Live warm-up state for an ephemeral user bot.
---

# EphemeralAgentStatus

Defined in [`parrot.manager.ephemeral`](../summaries/mod:parrot.manager.ephemeral.md).

```python
class EphemeralAgentStatus(BaseModel)
```

Live warm-up state for an ephemeral user bot.

Supports typed ownership: a bot may be owned by a human user
(``owner_kind="user"``) or an agent (``owner_kind="agent"``).
The legacy ``user_id: int`` constructor path is preserved via a
``model_validator`` that converts ``user_id`` → ``owner_id``/
``owner_kind="user"`` automatically (backward compatibility).

Attributes:
    chatbot_id: Canonical string form of the bot's UUID.
    owner_id: Canonical owner identifier (str form of user_id for users,
        or e.g. "agent:parent-123" for agent-owned bots).
    owner_kind: "user" for human-owned, "agent" for agent-owned sub-bots.
    phase: Current lifecycle phase.
    progress: Per-subsystem progress dict (tools / mcp / rag).
    error: Human-readable error message, set when phase == "error".
    created_at: UTC timestamp of registry insertion.
    expires_at: UTC timestamp after which the bot may be swept.
    rag_mode: Optional RAG mode used during warm-up.

## Methods

- `def user_id(self) -> Optional[int]` — Backward-compatible alias returning the int user ID.
