---
type: Wiki Summary
title: parrot.human.channels.cli
id: mod:parrot.human.channels.cli
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: CLI Human Channel for AI-Parrot HITL.
relates_to:
- concept: class:parrot.human.channels.cli.CLIDaemonHumanChannel
  rel: defines
- concept: class:parrot.human.channels.cli.CLIHumanChannel
  rel: defines
- concept: mod:parrot.human.channels.base
  rel: references
- concept: mod:parrot.human.models
  rel: references
---

# `parrot.human.channels.cli`

CLI Human Channel for AI-Parrot HITL.

Interactive terminal channel that renders questions using Rich
and captures responses via stdin. Supports two modes:

1. INTERACTIVE (default): Prompt appears directly in the terminal
   where the agent runs. Ideal for development and active monitoring.

2. DAEMON: Questions are published to a Redis queue. A separate
   CLI companion process (cli_companion.py) reads and responds.
   Used when the agent runs as a background service.

The CLI channel is "local" by definition — the human who responds
is whoever has access to the terminal. The recipient ID is typically
"local" or a user identifier for the daemon queue.

## Classes

- **`CLIHumanChannel(HumanChannel)`** — Interactive CLI channel for Human-in-the-Loop.
- **`CLIDaemonHumanChannel(HumanChannel)`** — CLI channel for when the agent runs as a daemon/background service.
