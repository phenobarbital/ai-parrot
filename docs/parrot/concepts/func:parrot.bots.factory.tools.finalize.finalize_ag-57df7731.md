---
type: Concept
title: finalize_agent_registration()
id: func:parrot.bots.factory.tools.finalize.finalize_agent_registration
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Write the YAML, reload the registry, and return the registration result.
---

# finalize_agent_registration

```python
async def finalize_agent_registration(definition: AgentDefinition, category: str='general') -> Dict[str, Any]
```

Write the YAML, reload the registry, and return the registration result.

Returns a dict with the YAML path and whether the registry picked up the
new definition (the registry skips ``enabled=False`` configs silently).
