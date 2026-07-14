---
type: Wiki Entity
title: LongTermMemoryMixin
id: class:parrot.memory.unified.mixin.LongTermMemoryMixin
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Single opt-in mixin for long-term memory in any bot/agent.
---

# LongTermMemoryMixin

Defined in [`parrot.memory.unified.mixin`](../summaries/mod:parrot.memory.unified.mixin.md).

```python
class LongTermMemoryMixin
```

Single opt-in mixin for long-term memory in any bot/agent.

Provides unified episodic + skill + conversation memory without
requiring the bot to manage individual subsystems.

MRO note: place before ``AbstractBot`` (or ``Agent``) in the class
definition so this mixin's methods take priority in the resolution order:

    class MyAgent(LongTermMemoryMixin, Agent):
        enable_long_term_memory = True

Configuration attributes (override in the subclass or via kwargs):
    enable_long_term_memory: Master toggle — all methods are no-ops when False.
    episodic_inject_warnings: Retrieve past failure warnings.
    episodic_auto_record: Record interactions to episodic memory.
    episodic_max_warnings: Maximum failure warnings per context.
    skill_inject_context: Retrieve relevant skills into context.
    skill_auto_extract: Auto-extract skills from successful interactions.
    skill_expose_tools: Register skill tools with the agent's tool manager.
    skill_max_context: Maximum skills per context.
    memory_max_context_tokens: Total token budget for assembled context.

## Methods

- `async def get_memory_context(self, query: str, user_id: str, session_id: str) -> str` — Return assembled memory context as an injectable prompt string.
