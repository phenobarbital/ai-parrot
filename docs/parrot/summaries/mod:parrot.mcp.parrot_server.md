---
type: Wiki Summary
title: parrot.mcp.parrot_server
id: mod:parrot.mcp.parrot_server
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Utilities for starting the MCP server inside the aiohttp application.
relates_to:
- concept: class:parrot.mcp.parrot_server.ParrotMCPServer
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.mcp.config
  rel: references
- concept: mod:parrot.mcp.server
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
---

# `parrot.mcp.parrot_server`

Utilities for starting the MCP server inside the aiohttp application.

## Classes

- **`ParrotMCPServer`** — Manage lifecycle of multiple MCP servers (multi-transport) attached to an aiohttp app.
