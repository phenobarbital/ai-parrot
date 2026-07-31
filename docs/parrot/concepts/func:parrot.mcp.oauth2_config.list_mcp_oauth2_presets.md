---
type: Concept
title: list_mcp_oauth2_presets()
id: func:parrot.mcp.oauth2_config.list_mcp_oauth2_presets
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return all registered MCP OAuth2 presets.
---

# list_mcp_oauth2_presets

```python
def list_mcp_oauth2_presets() -> list[MCPOAuth2Preset]
```

Return all registered MCP OAuth2 presets.

Returns:
    List of all :class:`MCPOAuth2Preset` instances.

Example:
    >>> presets = list_mcp_oauth2_presets()
    >>> [p.name for p in presets]
    ['netsuite', 'fireflies']
