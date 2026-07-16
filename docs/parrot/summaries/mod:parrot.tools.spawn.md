---
type: Wiki Summary
title: parrot.tools.spawn
id: mod:parrot.tools.spawn
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: SpawnSubAgentTool — ephemeral sub-agent spawner (FEAT-208).
relates_to:
- concept: class:parrot.tools.spawn.SpawnSubAgentInput
  rel: defines
- concept: class:parrot.tools.spawn.SpawnSubAgentTool
  rel: defines
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.tools.spawn`

SpawnSubAgentTool — ephemeral sub-agent spawner (FEAT-208).

Provides a first-class tool that an agent can invoke to:
1. Spawn an ephemeral sub-agent with a restricted tool subset.
2. Execute a single task with a configurable timeout.
3. Tear down the sub-agent unconditionally (success, error, or timeout).

The tool orchestrates the existing ``BotManager`` lifecycle methods
(generalized for typed ownership by TASK-1387/TASK-1388):
  create_ephemeral_user_bot → poll phase=="ready" → invoke(timeout) → discard.

Usage::

    tool = SpawnSubAgentTool(
        bot_manager=app["bot_manager"],
        owner_id="agent:my-orchestrator",
        allowed_tools=["search_docs", "get_weather"],
    )
    result = await tool.execute(
        task="Summarize the latest market news.",
        tools=["search_docs"],
        timeout=60,
    )

## Classes

- **`SpawnSubAgentInput(BaseModel)`** — Input schema for SpawnSubAgentTool.
- **`SpawnSubAgentTool(AbstractTool)`** — Spawn an ephemeral sub-agent to execute a single task.
