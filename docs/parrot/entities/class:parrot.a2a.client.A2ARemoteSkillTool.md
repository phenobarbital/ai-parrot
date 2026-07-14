---
type: Wiki Entity
title: A2ARemoteSkillTool
id: class:parrot.a2a.client.A2ARemoteSkillTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Wraps a specific skill from a remote A2A agent as a tool.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# A2ARemoteSkillTool

Defined in [`parrot.a2a.client`](../summaries/mod:parrot.a2a.client.md).

```python
class A2ARemoteSkillTool(AbstractTool)
```

Wraps a specific skill from a remote A2A agent as a tool.

Properly inherits from AbstractTool for ToolManager compatibility.
Dynamically generates input schema from the skill's input_schema.

## Methods

- `def clone(self) -> 'A2ARemoteSkillTool'` — Clone this tool (shares the client and skill references).
