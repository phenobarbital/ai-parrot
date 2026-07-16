---
type: Wiki Entity
title: SpawnSubAgentTool
id: class:parrot.tools.spawn.SpawnSubAgentTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spawn an ephemeral sub-agent to execute a single task.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# SpawnSubAgentTool

Defined in [`parrot.tools.spawn`](../summaries/mod:parrot.tools.spawn.md).

```python
class SpawnSubAgentTool(AbstractTool)
```

Spawn an ephemeral sub-agent to execute a single task.

Creates a short-lived sub-agent owned by the calling agent, executes
one task with a restricted tool subset and a timeout, then discards the
sub-agent — regardless of success, error, or timeout.

The tool **never** calls ``promote_user_bot``; all sub-agents are
ephemeral and discarded after their task completes.

Args:
    bot_manager: The ``BotManager`` instance (injected via constructor —
        testable without an aiohttp app).
    owner_id: Canonical string ID of the parent agent that owns the
        sub-agent (e.g. ``"agent:orchestrator-001"``).
    allowed_tools: Allowlist of tool names the parent authorises for
        sub-agents.  The sub-agent receives only the intersection of
        this list and the ``tools`` requested in the call.
    name: Tool name (default: ``"spawn_sub_agent"``).
    description: Tool description override.
    routing_meta: Routing hints for the CapabilityRegistry.  The key
        ``"requires_grant"`` is reserved for future HITL grant
        enforcement (FEAT-grants); set but not enforced here.
