---
type: Wiki Summary
title: parrot.cli.agent_repl
id: mod:parrot.cli.agent_repl
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Click command entry point for the AI-Parrot agent REPL.
relates_to:
- concept: func:parrot.cli.agent_repl.agent
  rel: defines
- concept: mod:parrot.cli.identity
  rel: references
- concept: mod:parrot.cli.loaders
  rel: references
- concept: mod:parrot.cli.renderer
  rel: references
- concept: mod:parrot.cli.repl
  rel: references
---

# `parrot.cli.agent_repl`

Click command entry point for the AI-Parrot agent REPL.

Provides the ``parrot agent`` subcommand. Resolves the agent (standalone or
server mode), builds ``REPLConfig``, and launches ``AgentREPL.run()``.

The function name must be ``agent`` to match the LazyGroup key:
``cli._lazy_commands = {..., "agent": "parrot.cli.agent_repl"}``.
``LazyGroup.get_command()`` uses ``getattr(mod, cmd_name)`` — i.e.
``getattr(module, "agent")``.

## Functions

- `def agent(name: Optional[str], list_agents: bool, server: Optional[str], no_stream: bool) -> None` — Interactive REPL for AI-Parrot agents.
