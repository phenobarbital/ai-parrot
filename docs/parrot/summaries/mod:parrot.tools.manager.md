---
type: Wiki Summary
title: parrot.tools.manager
id: mod:parrot.tools.manager
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot.tools.manager
relates_to:
- concept: class:parrot.tools.manager.ToolDefinition
  rel: defines
- concept: class:parrot.tools.manager.ToolFormat
  rel: defines
- concept: class:parrot.tools.manager.ToolManager
  rel: defines
- concept: class:parrot.tools.manager.ToolNameCollisionError
  rel: defines
- concept: class:parrot.tools.manager.ToolSchemaAdapter
  rel: defines
- concept: mod:parrot.a2a.models
  rel: references
- concept: mod:parrot.auth.confirmation
  rel: references
- concept: mod:parrot.auth.exceptions
  rel: references
- concept: mod:parrot.auth.grants
  rel: references
- concept: mod:parrot.auth.permission
  rel: references
- concept: mod:parrot.auth.resolver
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot.tools.discovery
  rel: references
- concept: mod:parrot.tools.mcp_mixin
  rel: references
- concept: mod:parrot.tools.registry
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
- concept: mod:parrot_tools.math
  rel: references
---

# `parrot.tools.manager`

## Classes

- **`ToolDefinition`** — Data structure for tool definition.
- **`ToolNameCollisionError(ValueError)`** — Raised when two toolkits try to register the same tool name.
- **`ToolFormat(Enum)`** — Enum for different tool format requirements by LLM providers.
- **`ToolSchemaAdapter`** — Adapter class to convert tool schemas between different LLM provider formats.
- **`ToolManager(MCPToolManagerMixin)`** — Unified tool manager for handling tools across AbstractBot and AbstractClient.
