---
type: Wiki Summary
title: parrot.tools.mcp_mixin
id: mod:parrot.tools.mcp_mixin
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: MCP Tool Manager Mixin - Adds MCP server capabilities to ToolManager.
relates_to:
- concept: class:parrot.tools.mcp_mixin.MCPToolManagerMixin
  rel: defines
- concept: mod:parrot.mcp.client
  rel: references
- concept: mod:parrot.mcp.context
  rel: references
- concept: mod:parrot.mcp.integration
  rel: references
---

# `parrot.tools.mcp_mixin`

MCP Tool Manager Mixin - Adds MCP server capabilities to ToolManager.

This mixin provides methods to:
- Add/remove MCP servers
- Register MCP tools as proxy tools
- Generate OpenAI-like MCP definitions for native injection
- Manage MCP server configurations

Usage:
    The mixin is automatically applied to ToolManager. Use it through
    any agent's tool_manager:
    
    ```python
    agent = BasicAgent(name="Demo", role="Assistant", goal="Test")
    await agent.tool_manager.add_mcp_server(config)
    ```

## Classes

- **`MCPToolManagerMixin`** — Mixin to add MCP capabilities to ToolManager.
