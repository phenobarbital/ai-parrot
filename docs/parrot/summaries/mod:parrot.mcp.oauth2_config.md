---
type: Wiki Summary
title: parrot.mcp.oauth2_config
id: mod:parrot.mcp.oauth2_config
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: MCP OAuth2 configuration models and presets registry.
relates_to:
- concept: class:parrot.mcp.oauth2_config.MCPOAuth2Config
  rel: defines
- concept: class:parrot.mcp.oauth2_config.MCPOAuth2GrantType
  rel: defines
- concept: class:parrot.mcp.oauth2_config.MCPOAuth2Preset
  rel: defines
- concept: func:parrot.mcp.oauth2_config.get_mcp_oauth2_preset
  rel: defines
- concept: func:parrot.mcp.oauth2_config.list_mcp_oauth2_presets
  rel: defines
---

# `parrot.mcp.oauth2_config`

MCP OAuth2 configuration models and presets registry.

Provides ``MCPOAuth2Config`` (per-server OAuth2 settings) and
``MCPOAuth2Preset`` (pre-built provider templates). Presets follow the
same in-code registry pattern as ``MCPServerDescriptor``.

## Classes

- **`MCPOAuth2GrantType(str, Enum)`** — OAuth2 grant types supported for MCP server authentication.
- **`MCPOAuth2Config(BaseModel)`** — OAuth2 configuration for a single MCP server connection.
- **`MCPOAuth2Preset(BaseModel)`** — Pre-built OAuth2 configuration template for a known MCP provider.

## Functions

- `def get_mcp_oauth2_preset(name: str) -> MCPOAuth2Preset | None` — Look up an MCP OAuth2 preset by its registry slug.
- `def list_mcp_oauth2_presets() -> list[MCPOAuth2Preset]` — Return all registered MCP OAuth2 presets.
