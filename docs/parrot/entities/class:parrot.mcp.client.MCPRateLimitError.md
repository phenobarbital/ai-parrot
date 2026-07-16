---
type: Wiki Entity
title: MCPRateLimitError
id: class:parrot.mcp.client.MCPRateLimitError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Raised when an MCP server rejects a request with a rate-limit error.
---

# MCPRateLimitError

Defined in [`parrot.mcp.client`](../summaries/mod:parrot.mcp.client.md).

```python
class MCPRateLimitError(MCPConnectionError)
```

Raised when an MCP server rejects a request with a rate-limit error.

Subclasses :class:`MCPConnectionError` so existing ``except`` blocks keep
working, while callers that want backoff can catch this type specifically
and honour ``retry_after``.

Attributes:
    retry_after: Suggested seconds to wait before retrying, already
        normalized to a delay relative to *now* (absolute epoch hints are
        converted). ``None`` when the server gave no usable hint.
    code: The JSON-RPC error code (usually ``-32429``).
    raw_error: The original JSON-RPC ``error`` object from the server.
