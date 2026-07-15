---
type: Wiki Summary
title: parrot_formdesigner.services.fieldsync_schema
id: mod:parrot_formdesigner.services.fieldsync_schema
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: DDL canónico para el schema ``fieldsync`` — idempotente, sin migraciones.
relates_to:
- concept: class:parrot_formdesigner.services.fieldsync_schema.FieldsyncSchemaManager
  rel: defines
---

# `parrot_formdesigner.services.fieldsync_schema`

DDL canónico para el schema ``fieldsync`` — idempotente, sin migraciones.

El schema ``fieldsync`` es el *system of record* de FEAT-302:

- ``fieldsync.projects`` — proyectos internos (contienen ``accounting_code``
  = cost center propio; UNIQUE por ``(client_id, accounting_code)``).
- ``fieldsync.workday_cost_center_mappings`` — mapeo de salida hacia Workday;
  un proyecto → un código Workday (UNIQUE por ``project_id``).
- ``fieldsync.auth_policies`` — policies ABAC/PBAC persistidas como JSONB;
  compatibles con el formato YAML del engine de nav-auth.

Diseño:
- NUNCA se lee ni escribe directamente sobre ``networkninja.projects``.
  El seed inicial (scripts/seed_fieldsync_projects.py) lee de allí solo
  para poblar ``fieldsync.projects``; después este schema es autónomo.
- DDL 100% idempotente: ``CREATE SCHEMA IF NOT EXISTS`` +
  ``CREATE TABLE IF NOT EXISTS``; segunda ejecución no falla.
- Sin framework de migraciones; columnas añadidas en futuras tasks con
  ALTER TABLE idempotente o un script de migración explícito.

Uso::

    pool = await asyncpg.create_pool(dsn=...)
    schema_mgr = FieldsyncSchemaManager(pool)
    await schema_mgr.initialize()  # crea schema + 3 tablas si no existen

## Classes

- **`FieldsyncSchemaManager`** — Apply the canonical ``fieldsync`` DDL to a Postgres database.
