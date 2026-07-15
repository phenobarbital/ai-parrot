---
type: Wiki Entity
title: FlowContext
id: class:parrot.bots.flows.core.context.FlowContext
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Execution state tracker for a single flow/crew run.
---

# FlowContext

Defined in [`parrot.bots.flows.core.context`](../summaries/mod:parrot.bots.flows.core.context.md).

```python
class FlowContext
```

Execution state tracker for a single flow/crew run.

Tracks which nodes have completed, their results and responses,
and metadata for each node's execution. Provides helpers to
determine whether a node's dependencies are satisfied and to
build its input payload.

Primary field: ``node_metadata`` (was ``agent_metadata`` in
``parrot.bots.orchestration.crew.FlowContext``). The old name
is kept as a ``@property`` alias for backward compatibility.

Args:
    initial_task: The initial prompt/task string given to the flow.

## Methods

- `def resolve_agent(self, agent_ref: AgentRef) -> AgentLike` — Resolve an agent reference to a live agent instance.
- `def can_execute(self, _node_id: str, dependencies: Set[str]) -> bool` — Return True if all ``dependencies`` are in ``completed_tasks``.
- `def mark_completed(self, node_id: str, result: Any=None, response: Any=None, metadata: Optional[NodeExecutionInfo]=None) -> None` — Record that a node has completed and store its outputs.
- `def mark_failed(self, node_id: str, error: Exception, metadata: Optional[NodeExecutionInfo]=None) -> None` — Record that a node has failed and store the error.
- `def get_input_for_node(self, node_id: str, dependencies: Set[str]) -> Dict[str, Any]` — Prepare the input payload for a node.
- `def agent_metadata(self) -> Dict[str, NodeExecutionInfo]` — Alias for ``node_metadata`` (backward compat with ``crew.FlowContext``).
- `def get_input_for_agent(self, agent_name: str, dependencies: Set[str]) -> Dict[str, Any]` — Alias for ``get_input_for_node()`` (backward compat with ``crew.FlowContext``).
