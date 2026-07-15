---
type: Concept
title: create_google_maps_mcp_server()
id: func:parrot.mcp.integration.create_google_maps_mcp_server
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Create configuration for Google Maps MCP server.
---

# create_google_maps_mcp_server

```python
def create_google_maps_mcp_server(name: str='google-maps', **kwargs) -> MCPServerConfig
```

Create configuration for Google Maps MCP server.

This MCP server connects to Google Maps Platform.
It automatically installs the @googlemaps/code-assist-mcp package using npx.

Args:
    name: Server name
    **kwargs: Additional MCPServerConfig parameters

Returns:
    MCPServerConfig configured for Google Maps
