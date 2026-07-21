---
type: Concept
title: discover_telegram_commands()
id: func:parrot.integrations.telegram.decorators.discover_telegram_commands
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Scan an agent instance for methods decorated with @telegram_command.
---

# discover_telegram_commands

```python
def discover_telegram_commands(agent: Any) -> List[Dict[str, Any]]
```

Scan an agent instance for methods decorated with @telegram_command.

Returns a list of dicts, each containing:
    - command: str (e.g. "question")
    - description: str
    - parse_mode: str
    - method_name: str (the actual method name on the agent)
    - method: bound method reference
