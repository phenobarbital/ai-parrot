---
type: Wiki Entity
title: ProjectService
id: class:parrot_formdesigner.services.project_service.ProjectService
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: CRUD service for ``fieldsync.projects`` and Workday mappings.
---

# ProjectService

Defined in [`parrot_formdesigner.services.project_service`](../summaries/mod:parrot_formdesigner.services.project_service.md).

```python
class ProjectService
```

CRUD service for ``fieldsync.projects`` and Workday mappings.

Args:
    pool: asyncpg pool (or fake pool for tests).

Example::

    svc = ProjectService(pool)
    proj = await svc.create_project(
        accounting_code="ACC-001",
        name="My Project",
        client_id=42,
        org_id=7,
        tenant="acme",
    )
    await svc.map_to_workday(proj.project_id, "WD-12345", tenant="acme")

## Methods

- `async def create_project(self, *, accounting_code: str, name: str | None=None, client_id: int, org_id: int | None=None, tenant: str | None=None) -> Project` — Create a new project in ``fieldsync.projects``.
- `async def get_project(self, project_id: int, *, org_id: int, tenant: str | None=None) -> Project` — Retrieve a project by its primary key, scoped to ``org_id``.
- `async def list_projects(self, *, org_id: int, client_id: int | None=None, tenant: str | None=None) -> list[Project]` — List projects within ``org_id`` (hard isolation), optionally by client.
- `async def map_to_workday(self, project_id: int, workday_code: str, *, tenant: str | None=None, direction: str='internal_to_workday') -> WorkdayCostCenterMapping` — Create or update a Workday cost center mapping for a project.
