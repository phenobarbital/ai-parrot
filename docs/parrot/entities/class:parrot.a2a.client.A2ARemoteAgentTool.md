---
type: Wiki Entity
title: A2ARemoteAgentTool
id: class:parrot.a2a.client.A2ARemoteAgentTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wraps a remote A2A agent as a tool that can be used by local agents.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# A2ARemoteAgentTool

Defined in [`parrot.a2a.client`](../summaries/mod:parrot.a2a.client.md).

```python
class A2ARemoteAgentTool(AbstractTool)
```

Wraps a remote A2A agent as a tool that can be used by local agents.

This creates a tool that, when invoked, sends the query to the remote agent.
Properly inherits from AbstractTool for ToolManager compatibility.

## Methods

- `def clone(self) -> 'A2ARemoteAgentTool'` — Clone this tool (shares the client reference).
