---
type: Wiki Summary
title: parrot.integrations.telegram.mcp_commands
id: mod:parrot.integrations.telegram.mcp_commands
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Telegram commands for per-user HTTP MCP server management.
relates_to:
- concept: func:parrot.integrations.telegram.mcp_commands.add_mcp_handler
  rel: defines
- concept: func:parrot.integrations.telegram.mcp_commands.list_mcp_handler
  rel: defines
- concept: func:parrot.integrations.telegram.mcp_commands.register_mcp_commands
  rel: defines
- concept: func:parrot.integrations.telegram.mcp_commands.rehydrate_user_mcp_servers
  rel: defines
- concept: func:parrot.integrations.telegram.mcp_commands.remove_mcp_handler
  rel: defines
- concept: mod:parrot.handlers.vault_utils
  rel: references
- concept: mod:parrot.integrations.telegram.mcp_persistence
  rel: references
- concept: mod:parrot.mcp.client
  rel: references
- concept: mod:parrot.tools.manager
  rel: references
---

# `parrot.integrations.telegram.mcp_commands`

Telegram commands for per-user HTTP MCP server management.

Lets an end user attach their own HTTP-based MCP server (for example
Fireflies.ai) to the agent *for their session only*. Credentials are
split into a **non-secret public config** (persisted in DocumentDB via
:class:`~parrot.integrations.telegram.mcp_persistence.TelegramMCPPersistenceService`)
and a **secret part** (stored in the Navigator Vault via
:func:`~parrot.handlers.vault_utils.store_vault_credential`).  Secrets are
never written to Redis, logs, or any unencrypted store.

Commands exposed on the wrapper router:

* ``/add_mcp <json>`` — add an HTTP MCP server.
* ``/list_mcp`` — list this user's registered servers (no secrets).
* ``/remove_mcp <name>`` — disconnect and forget a server.

The JSON payload mirrors ``MCPClientConfig`` but only accepts the
fields that make sense for remote HTTP MCP servers driven by a token.
A minimal example::

    /add_mcp {
      "name": "fireflies",
      "url": "https://api.fireflies.ai/mcp",
      "auth_scheme": "bearer",
      "token": "sk-..."
    }

``name`` is used as the DocumentDB compound key and as the MCP client id,
so callers can later remove or re-add the server by that name.

## Functions

- `async def rehydrate_user_mcp_servers(tool_manager: Optional['ToolManager'], user_id: str) -> int` — Re-attach every persisted MCP server to ``tool_manager``.
- `async def add_mcp_handler(message: Message, tool_manager_resolver: ToolManagerResolver) -> None` — Handle ``/add_mcp <json>``.
- `async def list_mcp_handler(message: Message) -> None` — Handle ``/list_mcp`` — show the user's saved servers (no secrets).
- `async def remove_mcp_handler(message: Message, tool_manager_resolver: ToolManagerResolver) -> None` — Handle ``/remove_mcp <name>``.
- `def register_mcp_commands(router: Router, tool_manager_resolver: ToolManagerResolver) -> None` — Wire the three MCP commands on *router*.
