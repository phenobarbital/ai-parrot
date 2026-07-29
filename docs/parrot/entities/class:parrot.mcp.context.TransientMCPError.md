---
type: Wiki Entity
title: TransientMCPError
id: class:parrot.mcp.context.TransientMCPError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Transient MCP errors that should be retried.
---

# TransientMCPError

Defined in [`parrot.mcp.context`](../summaries/mod:parrot.mcp.context.md).

```python
class TransientMCPError(Exception)
```

Transient MCP errors that should be retried.

Use this for errors like connection timeouts, temporary server unavailability,
rate limiting, etc. The retry_on_errors decorator will automatically retry
operations that raise this exception.
