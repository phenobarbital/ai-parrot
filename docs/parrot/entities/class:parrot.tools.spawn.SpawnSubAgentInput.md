---
type: Wiki Entity
title: SpawnSubAgentInput
id: class:parrot.tools.spawn.SpawnSubAgentInput
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Input schema for SpawnSubAgentTool.
---

# SpawnSubAgentInput

Defined in [`parrot.tools.spawn`](../summaries/mod:parrot.tools.spawn.md).

```python
class SpawnSubAgentInput(BaseModel)
```

Input schema for SpawnSubAgentTool.

Attributes:
    task: The question / task for the ephemeral sub-agent.
    tools: Allowed tool names for the sub-agent.  Intersected with the
        parent's ``allowed_tools`` allowlist for defense in depth.
    model: LLM model override.  Inherits parent default when not set.
    system_prompt: System prompt injected into the sub-agent.
    timeout: Max seconds the sub-agent is allowed to run before the call
        is cancelled.  Defaults to 120 s.
    ttl_seconds: Ephemeral registry TTL.  Keep short (default 300 s /
        5 min) for sub-agents — they should be discarded well before this.
