---
type: Concept
title: get_mcp_oauth2_preset()
id: func:parrot.mcp.oauth2_config.get_mcp_oauth2_preset
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Look up an MCP OAuth2 preset by its registry slug.
---

# get_mcp_oauth2_preset

```python
def get_mcp_oauth2_preset(name: str) -> MCPOAuth2Preset | None
```

Look up an MCP OAuth2 preset by its registry slug.

Args:
    name: Registry slug of the preset (e.g. ``"netsuite"``).

Returns:
    The :class:`MCPOAuth2Preset` if found, ``None`` otherwise.

Example:
    >>> preset = get_mcp_oauth2_preset("netsuite")
    >>> preset.display_name
    'NetSuite'
