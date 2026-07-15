---
type: Concept
title: create_chrome_devtools_mcp_server()
id: func:parrot.mcp.integration.create_chrome_devtools_mcp_server
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Create configuration for Chrome DevTools MCP server.
---

# create_chrome_devtools_mcp_server

```python
def create_chrome_devtools_mcp_server(browser_url: str='http://127.0.0.1:9222', name: str='chrome-devtools', **kwargs) -> MCPServerConfig
```

Create configuration for Chrome DevTools MCP server.

This MCP server connects to a Chrome instance running with known remote debugging port.
It automatically installs the chrome-devtools-mcp package using npx.

Args:
    browser_url: URL where Chrome is listening for devtools protocol (default: http://127.0.0.1:9222)
    name: Server name
    **kwargs: Additional MCPServerConfig parameters

Returns:
    MCPServerConfig configured for Chrome DevTools
