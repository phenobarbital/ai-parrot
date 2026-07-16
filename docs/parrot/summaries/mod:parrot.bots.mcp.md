---
type: Wiki Summary
title: parrot.bots.mcp
id: mod:parrot.bots.mcp
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Simplified MCPAgent for backward compatibility.
relates_to:
- concept: class:parrot.bots.mcp.MCPAgent
  rel: defines
- concept: mod:parrot.bots.agent
  rel: references
---

# `parrot.bots.mcp`

Simplified MCPAgent for backward compatibility.

Since BasicAgent now has integrated MCP support, MCPAgent is now just
an alias to BasicAgent. This file maintains backward compatibility for
existing code that uses MCPAgent.

## Classes

- **`MCPAgent(BasicAgent)`** — An agent with MCP (Model Context Protocol) capabilities.
