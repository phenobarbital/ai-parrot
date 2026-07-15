---
type: Wiki Summary
title: parrot.cli
id: mod:parrot.cli
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Top-level CLI entrypoint for Parrot utilities.
relates_to:
- concept: class:parrot.cli.LazyGroup
  rel: defines
- concept: func:parrot.cli.cli
  rel: defines
---

# `parrot.cli`

Top-level CLI entrypoint for Parrot utilities.

Subcommands are lazy-imported so that 'parrot setup' and 'parrot conf init'
work on a fresh checkout without navconfig's env/ directory.

This package also provides the interactive agent REPL subpackage:

- ``parrot.cli.agent_repl`` — ``parrot agent`` Click command
- ``parrot.cli.renderer`` — Rich-based response renderer
- ``parrot.cli.repl`` — AgentREPL engine
- ``parrot.cli.loaders`` — StandaloneAgentLoader, ServerAgentProxy
- ``parrot.cli.commands`` — SlashCommandDispatcher

## Classes

- **`LazyGroup(click.Group)`** — Click group that imports subcommands on first invocation.

## Functions

- `def cli()` — Parrot command-line interface.
