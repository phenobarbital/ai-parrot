---
type: Concept
title: build_node_metadata()
id: func:parrot.bots.flows.core.result.build_node_metadata
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Create execution metadata for a node run.
---

# build_node_metadata

```python
def build_node_metadata(node_id: str, agent: Optional[Any], response: Optional[Any], output: Optional[Any], execution_time: float, status: str, error: Optional[str]=None) -> NodeExecutionInfo
```

Create execution metadata for a node run.

Mirrors ``build_agent_metadata()`` from ``parrot.models.crew`` but
returns a ``NodeExecutionInfo`` instead of ``AgentExecutionInfo``.

Args:
    node_id: Unique identifier for this node instance.
    agent: The agent object (used to extract name/provider/model).
    response: Raw response object from the agent.
    output: Extracted output value.
    execution_time: Wall-clock time for the execution.
    status: Status string (normalised to allowed literals).
    error: Error message if execution failed.

Returns:
    Populated ``NodeExecutionInfo`` instance.
