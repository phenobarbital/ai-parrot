---
type: Wiki Entity
title: ResultRetrievalTool
id: class:parrot.bots.flows.tools.ResultRetrievalTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Retrieval Tool for flows (AgentCrew, AgentsFlow).
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# ResultRetrievalTool

Defined in [`parrot.bots.flows.tools`](../summaries/mod:parrot.bots.flows.tools.md).

```python
class ResultRetrievalTool(AbstractTool)
```

Retrieval Tool for flows (AgentCrew, AgentsFlow).

Allows agents to look up detailed execution results from the
``ExecutionMemory`` of a running flow.  Supports three actions:

- ``list_agents``: List all agents with available results.
- ``get_agent_result``: Retrieve the full result text for a specific agent.
- ``search_results``: Semantic search across stored results (requires
    FAISS to be configured on the ``ExecutionMemory``).

Args:
    memory: The ``ExecutionMemory`` instance to query.

## Methods

- `def get_schema(self) -> Dict[str, Any]` — Return the JSON schema for this tool's parameters.
