---
type: Wiki Entity
title: OrgNode
id: class:parrot_formdesigner.services.org_graph.OrgNode
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A single node in the organizational hierarchy.
---

# OrgNode

Defined in [`parrot_formdesigner.services.org_graph`](../summaries/mod:parrot_formdesigner.services.org_graph.md).

```python
class OrgNode(BaseModel)
```

A single node in the organizational hierarchy.

Attributes:
    node_type: Type of the node (organization, client, program, etc.).
    node_id: String identifier unique within the ``node_type`` namespace.
    parent_id: String identifier of the parent node, or ``None`` for root.
    metadata: Arbitrary key-value metadata (name, client_id, etc.).
    children: Nested child nodes (populated up to requested ``depth``).
