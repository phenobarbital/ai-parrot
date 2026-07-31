---
type: Wiki Summary
title: parrot.cli.commands
id: mod:parrot.cli.commands
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Slash command dispatcher and built-in commands for the AI-Parrot agent REPL.
relates_to:
- concept: class:parrot.cli.commands.ConversationTurn
  rel: defines
- concept: class:parrot.cli.commands.SlashCommand
  rel: defines
- concept: class:parrot.cli.commands.SlashCommandDispatcher
  rel: defines
- concept: mod:parrot.bots.factory
  rel: references
- concept: mod:parrot.cli.repl
  rel: references
- concept: mod:parrot.human.channels
  rel: references
- concept: mod:parrot.human.manager
  rel: references
---

# `parrot.cli.commands`

Slash command dispatcher and built-in commands for the AI-Parrot agent REPL.

Provides ``SlashCommandDispatcher`` with built-in commands:
``/tools``, ``/info``, ``/clear``, ``/export``, ``/stream``, ``/help``,
``/quit`` (aliased as ``/exit``).

Forward reference note: ``AgentREPL`` is imported under ``TYPE_CHECKING``
only to avoid circular imports — the actual type is resolved at runtime.

## Classes

- **`SlashCommand`** — A registered slash command.
- **`ConversationTurn`** — A single turn in the conversation history (used by ``/export``).
- **`SlashCommandDispatcher`** — Dispatches slash commands in the agent REPL.
