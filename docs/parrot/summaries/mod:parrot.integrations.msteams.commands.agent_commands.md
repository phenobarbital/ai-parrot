---
type: Wiki Summary
title: parrot.integrations.msteams.commands.agent_commands
id: mod:parrot.integrations.msteams.commands.agent_commands
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Core agent commands for MS Teams (FEAT-XXX).
relates_to:
- concept: class:parrot.integrations.msteams.commands.agent_commands.AgentCommandHandler
  rel: defines
- concept: mod:parrot.integrations.msteams.commands
  rel: references
- concept: mod:parrot.integrations.utils
  rel: references
- concept: mod:parrot.models.outputs
  rel: references
---

# `parrot.integrations.msteams.commands.agent_commands`

Core agent commands for MS Teams (FEAT-XXX).

Provides ``AgentCommandHandler``, which registers /function, /tool, /skill,
/commands, /help, /clear, /whoami, /question, and /call on the
``MSTeamsCommandRouter``, plus custom commands from ``config.commands``.

Usage::

    from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

    handler = AgentCommandHandler(agent, wrapper)
    handler.register(router)

## Classes

- **`AgentCommandHandler`** — Core agent commands for MS Teams.
