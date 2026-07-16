---
type: Wiki Entity
title: MCPAgent
id: class:parrot.bots.mcp.MCPAgent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: An agent with MCP (Model Context Protocol) capabilities.
relates_to:
- concept: class:parrot.bots.agent.BasicAgent
  rel: extends
---

# MCPAgent

Defined in [`parrot.bots.mcp`](../summaries/mod:parrot.bots.mcp.md).

```python
class MCPAgent(BasicAgent)
```

An agent with MCP (Model Context Protocol) capabilities.

DEPRECATED: This class is now just an alias to BasicAgent.
All agents (BasicAgent and subclasses) now have MCP support built-in.

For new code, use BasicAgent directly:
    agent = BasicAgent(name="my_agent")
    await agent.add_http_mcp_server(...)

This class is maintained for backward compatibility only.
