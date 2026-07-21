---
type: Concept
title: load_agent_definition()
id: func:parrot.bots.factory.tools.introspection.load_agent_definition
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return the ``BotConfig`` of a registered agent as a dict (for cloning).
---

# load_agent_definition

```python
async def load_agent_definition(name: str) -> Optional[Dict[str, Any]]
```

Return the ``BotConfig`` of a registered agent as a dict (for cloning).

Returns ``None`` if the agent is not registered or has no config (i.e. was
registered programmatically without YAML metadata).
