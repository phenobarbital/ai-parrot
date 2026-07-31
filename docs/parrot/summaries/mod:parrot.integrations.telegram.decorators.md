---
type: Wiki Summary
title: parrot.integrations.telegram.decorators
id: mod:parrot.integrations.telegram.decorators
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Decorator for declaring agent methods as Telegram bot commands.
relates_to:
- concept: func:parrot.integrations.telegram.decorators.discover_telegram_commands
  rel: defines
- concept: func:parrot.integrations.telegram.decorators.telegram_command
  rel: defines
---

# `parrot.integrations.telegram.decorators`

Decorator for declaring agent methods as Telegram bot commands.

## Functions

- `def telegram_command(command: str, description: str='', parse_mode: str='keyword') -> Callable` — Mark an agent method as a Telegram slash command.
- `def discover_telegram_commands(agent: Any) -> List[Dict[str, Any]]` — Scan an agent instance for methods decorated with @telegram_command.
