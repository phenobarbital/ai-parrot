---
type: Wiki Entity
title: NodeResult
id: class:parrot.bots.flows.core.result.NodeResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Per-node execution record for storage and vectorization.
---

# NodeResult

Defined in [`parrot.bots.flows.core.result`](../summaries/mod:parrot.bots.flows.core.result.md).

```python
class NodeResult
```

Per-node execution record for storage and vectorization.

Replaces ``AgentResult`` (``parrot.models.crew``) for all flow-internal
usage. Uses node-centric naming (``node_id``/``node_name``) while
providing backward-compat ``agent_id``/``agent_name`` property aliases.

The ``to_text()`` method produces rich text suitable for FAISS
vectorization, handling ``DataFrame``, ``dict``, ``list``, and plain
string results.

Args:
    node_id: Unique identifier for this node's execution.
    node_name: Human-readable name of the node/agent.
    task: The task/prompt string given to the node.
    result: The result value produced by the node.
    ai_message: Optional raw AI message from the LLM.
    metadata: Arbitrary additional metadata dict.
    execution_time: Wall-clock time for this execution (seconds).
    timestamp: UTC timestamp of this execution record.
    parent_execution_id: If this is a re-execution, the parent's ID.
    execution_id: Unique ID for this execution record (auto-generated).

## Methods

- `def agent_id(self) -> str` — Alias for ``node_id`` (backward compat with ``AgentResult.agent_id``).
- `def agent_name(self) -> str` — Alias for ``node_name`` (backward compat with ``AgentResult.agent_name``).
- `def to_dict(self) -> Dict[str, Any]` — Serialise to a plain, JSON-safe dictionary.
- `def to_text(self) -> str` — Convert execution result to rich text for FAISS vectorization.
