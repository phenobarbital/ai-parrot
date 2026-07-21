---
type: Concept
title: write_agent_yaml()
id: func:parrot.bots.factory.tools.finalize.write_agent_yaml
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Persist an ``AgentDefinition`` as a YAML file under ``agents/<category>/``.
---

# write_agent_yaml

```python
async def write_agent_yaml(definition: AgentDefinition, category: str='general') -> Path
```

Persist an ``AgentDefinition`` as a YAML file under ``agents/<category>/``.

Delegates to ``AgentRegistry.create_agent_definition`` so the on-disk
layout matches what the registry's YAML loader expects.
