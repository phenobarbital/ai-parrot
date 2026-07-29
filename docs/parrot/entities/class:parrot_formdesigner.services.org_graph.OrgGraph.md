---
type: Wiki Entity
title: OrgGraph
id: class:parrot_formdesigner.services.org_graph.OrgGraph
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Full organizational graph for a tenant.
---

# OrgGraph

Defined in [`parrot_formdesigner.services.org_graph`](../summaries/mod:parrot_formdesigner.services.org_graph.md).

```python
class OrgGraph(BaseModel)
```

Full organizational graph for a tenant.

Attributes:
    org_id: Numeric identifier of the organization.
    tenant: Tenant slug (program slug from navigator-auth).
    root: Root ``OrgNode`` (type ``"company"``); children are the tree.
