---
type: Wiki Summary
title: parrot.handlers.mcp_helper
id: mod:parrot.handlers.mcp_helper
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: MCP Helper HTTP Handler — discovery, activation, and management of MCP servers.
relates_to:
- concept: class:parrot.handlers.mcp_helper.MCPActiveHandler
  rel: defines
- concept: class:parrot.handlers.mcp_helper.MCPHelperHandler
  rel: defines
- concept: class:parrot.handlers.mcp_helper.MCPServerItemHandler
  rel: defines
- concept: func:parrot.handlers.mcp_helper.setup_mcp_helper_routes
  rel: defines
- concept: mod:parrot.handlers.mcp_persistence
  rel: references
- concept: mod:parrot.handlers.vault_utils
  rel: references
- concept: mod:parrot.mcp.registry
  rel: references
- concept: mod:parrot.tools.manager
  rel: references
---

# `parrot.handlers.mcp_helper`

MCP Helper HTTP Handler — discovery, activation, and management of MCP servers.

Provides four endpoints under ``/api/v1/agents/chat/{agent_id}/mcp-servers``:

- ``GET  /mcp-servers``          — return the full catalog of pre-built helpers
- ``POST /mcp-servers``          — activate a server on the session ToolManager
- ``GET  /mcp-servers/active``   — list active MCP servers in the session
- ``DELETE /mcp-servers/{name}`` — deactivate a server

Routes are registered by :func:`setup_mcp_helper_routes`.

The activation flow:
1. Validate params via :class:`~parrot.mcp.registry.MCPServerRegistry`.
2. Separate secret params from non-secret params.
3. Encrypt secrets and store in DocumentDB (``user_credentials`` collection).
4. Call the corresponding ``create_*_mcp_server`` factory to build config.
5. Register on the session-scoped ToolManager.
6. Persist non-secret config via :class:`~parrot.handlers.mcp_persistence.MCPPersistenceService`.

## Classes

- **`MCPHelperHandler(BaseView)`** — HTTP handler for MCP server catalog listing and activation.
- **`MCPActiveHandler(BaseView)`** — HTTP handler that returns the currently active MCP servers in the session.
- **`MCPServerItemHandler(BaseView)`** — HTTP handler for deactivating a specific MCP server.

## Functions

- `def setup_mcp_helper_routes(app: web.Application) -> None` — Register MCP helper management routes on the aiohttp application.
