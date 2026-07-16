---
type: Concept
title: rehydrate_user_mcp_servers()
id: func:parrot.integrations.telegram.mcp_commands.rehydrate_user_mcp_servers
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Re-attach every persisted MCP server to ``tool_manager``.
---

# rehydrate_user_mcp_servers

```python
async def rehydrate_user_mcp_servers(tool_manager: Optional['ToolManager'], user_id: str) -> int
```

Re-attach every persisted MCP server to ``tool_manager``.

Called by the wrapper from ``_initialize_user_context`` so a process
restart or a fresh session does not make the user re-issue
``/add_mcp``. Loads public config from DocumentDB and secrets from the
Vault, then rebuilds each ``MCPClientConfig``.

Failures are logged per-server and do not abort the rehydration of the
remaining servers.

Args:
    tool_manager: The user's isolated :class:`~parrot.tools.manager.ToolManager`.
    user_id: Telegram user identifier (``tg:<telegram_id>``).

Returns:
    Number of MCP servers successfully registered.
