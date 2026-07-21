---
type: Concept
title: register_mcp_commands()
id: func:parrot.integrations.telegram.mcp_commands.register_mcp_commands
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wire the three MCP commands on *router*.
---

# register_mcp_commands

```python
def register_mcp_commands(router: Router, tool_manager_resolver: ToolManagerResolver) -> None
```

Wire the three MCP commands on *router*.

Args:
    router: aiogram ``Router`` owned by the Telegram wrapper.
    tool_manager_resolver: async callable returning the per-user
        ``ToolManager`` for a given ``Message`` (or ``None`` when
        the user's session has not been initialized yet). Provided
        by the wrapper so the handlers stay decoupled from the
        singleton/per-user-agent mode detail.
