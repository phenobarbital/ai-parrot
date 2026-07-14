---
type: Wiki Summary
title: parrot.mcp.cli
id: mod:parrot.mcp.cli
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot.mcp.cli
relates_to:
- concept: func:parrot.mcp.cli.mcp
  rel: defines
- concept: func:parrot.mcp.cli.serve
  rel: defines
- concept: mod:parrot.mcp.parrot_server
  rel: references
- concept: mod:parrot.mcp.server
  rel: references
- concept: mod:parrot.mcp.wrapper
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
---

# `parrot.mcp.cli`

## Functions

- `def mcp(ctx, config)` — MCP server commands.
- `def serve(config_file: str, transport: Optional[str], socket: Optional[str], port: Optional[int], log_level: str)` — Start an MCP server from a Python config file or YAML.
