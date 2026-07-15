---
type: Concept
title: raise_for_jsonrpc_error()
id: func:parrot.mcp.client.raise_for_jsonrpc_error
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Translate a JSON-RPC ``error`` object into the right exception.
---

# raise_for_jsonrpc_error

```python
def raise_for_jsonrpc_error(error: Dict[str, Any]) -> None
```

Translate a JSON-RPC ``error`` object into the right exception.

Rate-limit errors (code ``-32429`` or ``data.type == 'rate_limit_exceeded'``)
become :class:`MCPRateLimitError` carrying a normalized ``retry_after``;
everything else becomes a generic :class:`MCPConnectionError`.

Always raises — never returns normally.
