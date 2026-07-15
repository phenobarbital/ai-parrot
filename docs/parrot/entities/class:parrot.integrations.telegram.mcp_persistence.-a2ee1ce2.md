---
type: Wiki Entity
title: TelegramMCPPublicParams
id: class:parrot.integrations.telegram.mcp_persistence.TelegramMCPPublicParams
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Non-secret subset of an /add_mcp payload safe to persist in DocumentDB.
---

# TelegramMCPPublicParams

Defined in [`parrot.integrations.telegram.mcp_persistence`](../summaries/mod:parrot.integrations.telegram.mcp_persistence.md).

```python
class TelegramMCPPublicParams(BaseModel)
```

Non-secret subset of an /add_mcp payload safe to persist in DocumentDB.

Attributes:
    name: Server name (the command's JSON ``name``).
    url: HTTP(S) endpoint of the MCP server.
    transport: MCP transport protocol (default ``"http"``).
    description: Optional human-readable description.
    auth_scheme: Authentication scheme used (``"none"`` | ``"bearer"`` |
        ``"api_key"`` | ``"basic"``).
    api_key_header: Custom header name for ``api_key`` scheme only.
    use_bearer_prefix: Whether to add the ``Bearer `` prefix for
        ``api_key`` scheme.
    headers: Extra HTTP headers sent with every MCP request.
    allowed_tools: Whitelist of tool names; ``None`` means all tools.
    blocked_tools: Blacklist of tool names; ``None`` means none blocked.
