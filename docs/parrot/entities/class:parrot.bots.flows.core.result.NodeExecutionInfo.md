---
type: Wiki Entity
title: NodeExecutionInfo
id: class:parrot.bots.flows.core.result.NodeExecutionInfo
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Execution metadata for a single node in a flow/crew run.
---

# NodeExecutionInfo

Defined in [`parrot.bots.flows.core.result`](../summaries/mod:parrot.bots.flows.core.result.md).

```python
class NodeExecutionInfo
```

Execution metadata for a single node in a flow/crew run.

Primary fields use node-centric naming (``node_id``, ``node_name``).
Backward-compatible aliases (``agent_id``, ``agent_name``) are provided
as ``@property`` accessors so existing code continues to work.

Mirrors all fields of ``parrot.models.crew.AgentExecutionInfo``.

## Methods

- `def agent_id(self) -> str` — Alias for ``node_id`` (backward compatibility with AgentExecutionInfo).
- `def agent_name(self) -> str` — Alias for ``node_name`` (backward compatibility with AgentExecutionInfo).
- `def to_dict(self) -> Dict[str, Any]` — Serialise to a plain JSON-serialisable dictionary.
