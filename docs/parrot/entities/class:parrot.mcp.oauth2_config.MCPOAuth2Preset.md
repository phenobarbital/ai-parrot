---
type: Wiki Entity
title: MCPOAuth2Preset
id: class:parrot.mcp.oauth2_config.MCPOAuth2Preset
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pre-built OAuth2 configuration template for a known MCP provider.
---

# MCPOAuth2Preset

Defined in [`parrot.mcp.oauth2_config`](../summaries/mod:parrot.mcp.oauth2_config.md).

```python
class MCPOAuth2Preset(BaseModel)
```

Pre-built OAuth2 configuration template for a known MCP provider.

Presets supply default values for ``MCPOAuth2Config`` fields.  Callers
typically look up a preset by name, then override individual fields with
user-supplied values (e.g. ``client_id``).

Attributes:
    name: Registry slug (e.g. ``"netsuite"``).
    display_name: Human-readable name (e.g. ``"NetSuite"``).
    auth_url: Default authorization endpoint URL (may contain template vars).
    token_url: Default token endpoint URL (may contain template vars).
    scopes: Default scopes for this provider.
    grant_type: Default grant type.
    url_template: Template for the MCP server URL (``{account_id}`` etc.).
    required_params: Parameters the caller MUST supply.
