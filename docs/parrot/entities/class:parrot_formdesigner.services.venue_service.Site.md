---
type: Wiki Entity
title: Site
id: class:parrot_formdesigner.services.venue_service.Site
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: An intermediate work-area grouping inside a Store.
---

# Site

Defined in [`parrot_formdesigner.services.venue_service`](../summaries/mod:parrot_formdesigner.services.venue_service.md).

```python
class Site(BaseModel)
```

An intermediate work-area grouping inside a Store.

A Store may contain multiple Sites; a Site groups one or more Locations.
Owned by FieldSync (``fieldsync.sites``); tenant-isolated by ``org_id``.

Attributes:
    site_id: Auto-incremented serial PK.
    store_id: Identifier of the parent store (networkninja geography).
        Kept as ``str`` for parity with ``OrgNode.node_id``.
    client_id: Client this site belongs to.
    org_id: Organization identifier (hard-isolation key).
    name: Human-readable site name.
    is_active: Whether the site is currently active.
    tenant: Tenant slug (metadata, not stored in the table directly).
