---
type: Wiki Entity
title: FlowEdge
id: class:parrot.bots.flows.flow.flow.FlowEdge
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Programmatic transition edge between two nodes.
---

# FlowEdge

Defined in [`parrot.bots.flows.flow.flow`](../summaries/mod:parrot.bots.flows.flow.flow.md).

```python
class FlowEdge
```

Programmatic transition edge between two nodes.

Counterpart of the declarative ``EdgeDefinition`` for flows built with
``add_node()`` / ``add_edge()`` instead of a ``FlowDefinition``.

Attributes:
    from_: Source node_id.
    to: Target node_id.
    condition: One of ``EDGE_CONDITIONS``. ``"on_condition"`` requires a
        ``predicate``.
    predicate: Either a CEL expression string or a Python callable
        ``(source_result) -> bool`` evaluated against the source node's
        result when ``condition == "on_condition"``.
