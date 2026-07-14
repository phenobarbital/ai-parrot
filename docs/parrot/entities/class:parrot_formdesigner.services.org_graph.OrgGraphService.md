---
type: Wiki Entity
title: OrgGraphService
id: class:parrot_formdesigner.services.org_graph.OrgGraphService
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Build in-memory org-graph trees from navigator-auth + networkninja.
---

# OrgGraphService

Defined in [`parrot_formdesigner.services.org_graph`](../summaries/mod:parrot_formdesigner.services.org_graph.md).

```python
class OrgGraphService
```

Build in-memory org-graph trees from navigator-auth + networkninja.

Designed for read-only access. Enforces hard tenant isolation by always
filtering on ``org_id`` / ``client_id`` passed as parameters.

Args:
    pool: asyncpg pool (or compatible fake). When ``None``, falls back
        to creating a pool from ``FIELDSYNC_AUTH_RO_DSN`` env var.
        In unit tests pass a fake pool explicitly.

Example::

    svc = OrgGraphService(pool)
    graph = await svc.get_graph(7, tenant="acme")

## Methods

- `async def get_graph(self, org_id: int, *, tenant: str, depth: int=3) -> OrgGraph` — Build the full org graph for ``org_id`` / ``tenant``.
- `async def get_node(self, node_type: NodeType, node_id: str, *, tenant: str, org_id: int) -> OrgNode` — Retrieve a single node by type and ID, enforcing tenant isolation.
