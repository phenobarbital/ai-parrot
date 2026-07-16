---
type: Wiki Summary
title: parrot.cli.repl
id: mod:parrot.cli.repl
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: REPL engine for the AI-Parrot agent CLI.
relates_to:
- concept: class:parrot.cli.repl.AgentREPL
  rel: defines
- concept: class:parrot.cli.repl.REPLConfig
  rel: defines
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.cli.commands
  rel: references
- concept: mod:parrot.cli.renderer
  rel: references
- concept: mod:parrot.models.outputs
  rel: references
- concept: mod:parrot.models.responses
  rel: references
---

# `parrot.cli.repl`

REPL engine for the AI-Parrot agent CLI.

Provides ``AgentREPL`` — a ``prompt_toolkit``-based async read-eval-print loop
that interacts with a registered agent via ``ask()`` / ``ask_stream()``.

Also exports ``REPLConfig`` — a Pydantic v2 model holding session configuration.

## Classes

- **`REPLConfig(BaseModel)`** — Configuration for an agent REPL session.
- **`AgentREPL`** — Interactive REPL for agent conversation.
