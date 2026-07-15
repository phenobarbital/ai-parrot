---
type: Concept
title: build_agent_metadata()
id: func:parrot.models.crew.build_agent_metadata
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Create execution metadata for an agent run.
---

# build_agent_metadata

```python
def build_agent_metadata(agent_id: str, agent: Optional[Any], response: Optional[ResponseType], output: Optional[Any], execution_time: float, status: str, error: Optional[str]=None) -> AgentExecutionInfo
```

Create execution metadata for an agent run.
