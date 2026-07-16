---
type: Wiki Entity
title: Project
id: class:parrot_formdesigner.services.project_service.Project
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A project stored in ``fieldsync.projects``.
---

# Project

Defined in [`parrot_formdesigner.services.project_service`](../summaries/mod:parrot_formdesigner.services.project_service.md).

```python
class Project(BaseModel)
```

A project stored in ``fieldsync.projects``.

Attributes:
    project_id: Auto-incremented serial PK.
    name: Human-readable project name.
    accounting_code: Internal cost center code (source of truth).
    client_id: Client this project belongs to.
    org_id: Organization identifier.
    start_timestamp: Optional project start date.
    end_timestamp: Optional project end date.
    is_active: Whether the project is currently active.
    tenant: Tenant slug (metadata, not stored in the table directly).
