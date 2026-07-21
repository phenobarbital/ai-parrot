---
type: Wiki Summary
title: parrot.human.cli_companion
id: mod:parrot.human.cli_companion
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: CLI Companion for Human-in-the-Loop.
relates_to:
- concept: class:parrot.human.cli_companion.HITLCompanion
  rel: defines
- concept: func:parrot.human.cli_companion.main
  rel: defines
- concept: mod:parrot.human.channels.cli
  rel: references
- concept: mod:parrot.human.models
  rel: references
---

# `parrot.human.cli_companion`

CLI Companion for Human-in-the-Loop.

A standalone process that connects to Redis, listens for pending
HITL interactions, and lets the human respond interactively.

Used when agents run as daemon/background services and cannot
access stdin directly. The companion acts as a "chat client"
for the HITL system.

Usage:
    python -m parrot.human.cli_companion --user jesus --redis redis://localhost:6379

Features:
- Shows all pending questions on startup
- Listens for new questions via Redis pub/sub
- Renders questions using Rich (same UI as CLIHumanChannel)
- Sends responses back through Redis queues

## Classes

- **`HITLCompanion`** — Interactive CLI companion for the HITL daemon channel.

## Functions

- `def main() -> None` — CLI entry point.
