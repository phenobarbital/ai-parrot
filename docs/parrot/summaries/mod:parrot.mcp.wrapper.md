---
type: Wiki Summary
title: parrot.mcp.wrapper
id: mod:parrot.mcp.wrapper
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot.mcp.wrapper
relates_to:
- concept: func:parrot.mcp.wrapper.load_server_from_config
  rel: defines
- concept: func:parrot.mcp.wrapper.load_tool_class
  rel: defines
- concept: func:parrot.mcp.wrapper.resolve_config_value
  rel: defines
- concept: mod:parrot.mcp.simple_server
  rel: references
---

# `parrot.mcp.wrapper`

## Functions

- `def resolve_config_value(tool_name: str, key: str, value: Any) -> Any` — Resolve a configuration value against navconfig / os.environ.
- `def load_tool_class(tool_name: str)` — Dynamic loading of a tool class by its class name.
- `def load_server_from_config(config_path: str) -> SimpleMCPServer` — Load a SimpleMCPServer instance from a YAML configuration file.
