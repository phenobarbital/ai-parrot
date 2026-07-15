---
type: Concept
title: list_available_tools()
id: func:parrot.bots.factory.tools.introspection.list_available_tools
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return the catalog of standalone ``@tool`` functions discovered.
---

# list_available_tools

```python
async def list_available_tools() -> List[Dict[str, str]]
```

Return the catalog of standalone ``@tool`` functions discovered.

The factory currently relies on the toolkit catalog for capability
discovery; standalone tools surface here so builders can reference them
by name in ``tools.tools`` of an ``AgentDefinition``.
