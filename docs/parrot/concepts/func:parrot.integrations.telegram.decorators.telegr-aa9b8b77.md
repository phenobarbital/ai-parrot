---
type: Concept
title: telegram_command()
id: func:parrot.integrations.telegram.decorators.telegram_command
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Mark an agent method as a Telegram slash command.
---

# telegram_command

```python
def telegram_command(command: str, description: str='', parse_mode: str='keyword') -> Callable
```

Mark an agent method as a Telegram slash command.

The decorator stores metadata on the function via `_telegram_command`.
Registration with aiogram happens at bot startup (not at decoration time).

Args:
    command: Command name without leading slash (e.g. "question").
    description: One-line description shown in the Telegram menu.
    parse_mode: How to parse user input after the command.
        - "keyword": `/cmd key=val key2=val2` → method(**kwargs)
        - "positional": `/cmd arg1 arg2` → method(*args)
        - "raw": `/cmd <everything>` → method(text)
