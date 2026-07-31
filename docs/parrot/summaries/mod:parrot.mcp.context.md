---
type: Wiki Summary
title: parrot.mcp.context
id: mod:parrot.mcp.context
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: MCP Context Module.
relates_to:
- concept: class:parrot.mcp.context.MCPSessionManager
  rel: defines
- concept: class:parrot.mcp.context.ReadonlyContext
  rel: defines
- concept: class:parrot.mcp.context.TransientMCPError
  rel: defines
- concept: func:parrot.mcp.context.retry_on_errors
  rel: defines
---

# `parrot.mcp.context`

MCP Context Module.

Provides ReadonlyContext for context-aware tool access and MCPSessionManager
for session lifecycle management with retry logic.

## Classes

- **`ReadonlyContext(BaseModel)`** — Immutable context passed to tool operations.
- **`TransientMCPError(Exception)`** — Transient MCP errors that should be retried.
- **`MCPSessionManager`** — Manages session lifecycle and retry logic for MCP connections.

## Functions

- `def retry_on_errors(max_retries: int=3, base_wait: float=2.0) -> Callable[[F], F]` — Decorator for automatic retry on transient errors with exponential backoff.
