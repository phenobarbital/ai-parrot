---
type: Wiki Entity
title: OperatorCommandsMixin
id: class:parrot.integrations.telegram.operator_commands.OperatorCommandsMixin
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Operator-only Telegram commands for the autonomous harness.
---

# OperatorCommandsMixin

Defined in [`parrot.integrations.telegram.operator_commands`](../summaries/mod:parrot.integrations.telegram.operator_commands.md).

```python
class OperatorCommandsMixin
```

Operator-only Telegram commands for the autonomous harness.

This mixin adds 7 command handlers and the ``_register_operator_commands``
registration helper.  It is designed to be mixed into ``TelegramAgentWrapper``
via multiple-inheritance.

The mixin relies on the following attributes being present on ``self``:
- ``self.config``          — TelegramAgentConfig (with operator_chat_ids,
                             enable_operator_commands from TASK-1394)
- ``self.agent``           — AbstractBot instance
- ``self.conversations``   — Dict[int, ConversationMemory]
- ``self.app``             — aiohttp web.Application (may be None or dict)
- ``self.router``          — aiogram Router
- ``self.logger``          — standard Python logger
- ``_is_operator()``       — gate method added by TASK-1394
- ``_send_safe_message()`` — safe reply helper from wrapper.py
- ``_typing_indicator()``  — optional; used by /thread for Telegram UX.
                             When absent, /thread still works without indicator.

## Methods

- `async def handle_context(self, message: Message) -> None` — Handle /context — show the conversation shaping context (read-only).
- `async def handle_memory(self, message: Message) -> None` — Handle /memory — show recent conversation turns (read-only).
- `async def handle_model(self, message: Message) -> None` — Handle /model — show the agent's model name and LLM provider (read-only).
- `async def handle_mission(self, message: Message) -> None` — Handle /mission — show the heartbeat mission string (read-only).
- `async def handle_health(self, message: Message) -> None` — Handle /health — project heartbeat liveness.
- `async def handle_status(self, message: Message) -> None` — Handle /status — composite view of heartbeat and ephemeral sub-agents.
- `async def handle_thread(self, message: Message) -> None` — Handle /thread <task> — fork work to an ephemeral sub-agent (FEAT-208).
