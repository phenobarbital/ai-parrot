---
type: Wiki Summary
title: parrot_formdesigner.services.project_service
id: mod:parrot_formdesigner.services.project_service
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: ProjectService — CRUD sobre ``fieldsync.projects`` + mapping Workday.
relates_to:
- concept: class:parrot_formdesigner.services.project_service.DuplicateAccountingCodeError
  rel: defines
- concept: class:parrot_formdesigner.services.project_service.Project
  rel: defines
- concept: class:parrot_formdesigner.services.project_service.ProjectNotFoundError
  rel: defines
- concept: class:parrot_formdesigner.services.project_service.ProjectService
  rel: defines
- concept: class:parrot_formdesigner.services.project_service.WorkdayCostCenterMapping
  rel: defines
- concept: mod:parrot_formdesigner.services._db_utils
  rel: references
---

# `parrot_formdesigner.services.project_service`

ProjectService — CRUD sobre ``fieldsync.projects`` + mapping Workday.

Implementa el *system of record* de proyectos internos (FEAT-302 Module 2):
- ``create_project`` / ``get_project`` / ``list_projects``
- ``map_to_workday`` (upsert en ``fieldsync.workday_cost_center_mappings``)

Reglas de negocio confirmadas (§8 spec):
- ``accounting_code`` es el **cost center interno**; NUNCA se importa desde
  Workday (Workday es destino de salida, no fuente).
- UNIQUE ``(client_id, accounting_code)`` — duplicate → ``DuplicateAccountingCodeError``.
- ``map_to_workday`` hace UPSERT por ``project_id`` (un proyecto tiene como
  máximo un Workday mapping).
- NUNCA se escribe en ``networkninja.projects``.

Diseño:
- Pool inyectado en constructor → testable sin DB real.
- SQL 100% parametrizado ($1, $2…); nombres de tabla fijados en constantes.
- Pydantic v2 para modelos de datos.

Uso::

    svc = ProjectService(pool)
    proj = await svc.create_project(
        accounting_code="ACC-001",
        name="Q1 Campaign",
        client_id=42,
        org_id=7,
        tenant="acme",
    )
    mapping = await svc.map_to_workday(proj.project_id, "WD-99001", tenant="acme")

## Classes

- **`DuplicateAccountingCodeError(Exception)`** — Raised when ``(client_id, accounting_code)`` already exists.
- **`ProjectNotFoundError(Exception)`** — Raised when a project lookup returns no row.
- **`Project(BaseModel)`** — A project stored in ``fieldsync.projects``.
- **`WorkdayCostCenterMapping(BaseModel)`** — Mapping from an internal project to a Workday cost center code.
- **`ProjectService`** — CRUD service for ``fieldsync.projects`` and Workday mappings.
