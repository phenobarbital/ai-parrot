---
type: Wiki Summary
title: parrot.integrations.telegram.operator_commands
id: mod:parrot.integrations.telegram.operator_commands
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Operator-only Telegram commands for the autonomous harness (FEAT-210).
relates_to:
- concept: class:parrot.integrations.telegram.operator_commands.OperatorCommandsMixin
  rel: defines
- concept: mod:parrot.autonomous.heartbeat
  rel: references
- concept: mod:parrot.memory.abstract
  rel: references
---

# `parrot.integrations.telegram.operator_commands`

Operator-only Telegram commands for the autonomous harness (FEAT-210).

This module defines ``OperatorCommandsMixin`` — a mixin class that adds 7
operator-restricted command handlers to ``TelegramAgentWrapper``.  The mixin
is mixed in by TASK-1398 (wrapper.py) and its commands are registered via
``_register_operator_commands()``.

Commands implemented here:
- /context  — show the conversation's system-prompt / shaping context (read-only)
- /memory   — show recent conversation turns (read-only, limited to N)
- /model    — show the agent's model name and LLM provider (read-only)
- /mission  — show the heartbeat mission string (read-only; degrades if absent)
- /health   — project heartbeat liveness (degrades if FEAT-209 not wired)
- /status   — composite view: heartbeat + ephemeral sub-agents (each section degrades independently)
- /thread   — fork work to an ephemeral sub-agent (FEAT-208; degrades if absent)

All external feature imports (FEAT-208, FEAT-209) are guarded with
try/except ImportError so the wrapper starts cleanly even when those
features have not been merged or installed.

## Classes

- **`OperatorCommandsMixin`** — Operator-only Telegram commands for the autonomous harness.
