---
type: Wiki Summary
title: parrot.mcp.registry
id: mod:parrot.mcp.registry
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: MCP Server Registry — declarative catalog of pre-built MCP server helpers.
relates_to:
- concept: class:parrot.mcp.registry.ActivateMCPServerRequest
  rel: defines
- concept: class:parrot.mcp.registry.MCPParamType
  rel: defines
- concept: class:parrot.mcp.registry.MCPServerDescriptor
  rel: defines
- concept: class:parrot.mcp.registry.MCPServerParam
  rel: defines
- concept: class:parrot.mcp.registry.MCPServerRegistry
  rel: defines
- concept: class:parrot.mcp.registry.UserMCPServerConfig
  rel: defines
- concept: func:parrot.mcp.registry.get_factory_map
  rel: defines
- concept: mod:parrot.mcp.integration
  rel: references
---

# `parrot.mcp.registry`

MCP Server Registry — declarative catalog of pre-built MCP server helpers.

This module defines the data models and registry that describe each
``add_*_mcp_server`` helper method on :class:`~parrot.mcp.integration.MCPEnabledMixin`.
The registry is declarative (not reflection-based), so descriptions, param types,
and categories are explicit rather than inferred from signatures.

Usage::

    from parrot.mcp.registry import MCPServerRegistry, MCPParamType

    registry = MCPServerRegistry()
    servers = registry.list_servers()
    desc = registry.get_server("perplexity")
    params = registry.validate_params("perplexity", {"api_key": "sk-..."})

## Classes

- **`MCPParamType(str, Enum)`** — Type hint for an MCP server parameter.
- **`MCPServerParam(BaseModel)`** — Describes a single parameter accepted by an MCP server helper.
- **`MCPServerDescriptor(BaseModel)`** — Catalog entry describing a single pre-built MCP server helper.
- **`UserMCPServerConfig(BaseModel)`** — Persisted configuration for a user-activated MCP server.
- **`ActivateMCPServerRequest(BaseModel)`** — Request body for the POST (activate) endpoint.
- **`MCPServerRegistry`** — Catalog of pre-built MCP server helpers available for user activation.

## Functions

- `def get_factory_map() -> Dict[str, Any]` — Return the dispatch map from registry slug to ``create_*`` factory function.
