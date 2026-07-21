---
type: Wiki Summary
title: parrot_formdesigner.services.storage
id: mod:parrot_formdesigner.services.storage
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: PostgreSQL Form Storage for the forms abstraction layer.
relates_to:
- concept: class:parrot_formdesigner.services.storage.PostgresFormStorage
  rel: defines
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.core.style
  rel: references
- concept: mod:parrot_formdesigner.services._identifiers
  rel: references
- concept: mod:parrot_formdesigner.services.registry
  rel: references
---

# `parrot_formdesigner.services.storage`

PostgreSQL Form Storage for the forms abstraction layer.

Implements the FormStorage ABC using asyncpg for PostgreSQL persistence.
Forms are stored as JSONB, supporting versioning and UPSERT operations.

Schema, table name, and tenant are configurable. The default schema is
``navigator`` (NOT ``public``) and the default table is ``form_schemas``.
A tenant slug — when provided — overrides the schema at the SQL level so
the same storage instance can serve many tenants
(``epson.form_schemas``, ``pokemon.form_schemas``, …).

Table columns:
- id: UUID primary key
- form_id: VARCHAR
- version: VARCHAR
- schema_json: JSONB (serialized FormSchema)
- style_json: JSONB (serialized StyleSchema, optional)
- tenant: VARCHAR (nullable; physical-schema indicator captured for audit)
- created_at, updated_at: TIMESTAMPTZ
- created_by: VARCHAR (optional metadata)
- UNIQUE(form_id, version)

Usage (self-managed pool — recommended):
    storage = PostgresFormStorage(
        dsn="postgresql://user:pw@host/db",
        schema="navigator",
        table_name="form_schemas",
    )
    await storage.initialize()   # creates pool + DDL
    await storage.save(form_schema)
    await storage.close()        # closes pool

Usage (externally-managed pool — backward compatible):
    pool = await asyncpg.create_pool(dsn="postgresql://...")
    storage = PostgresFormStorage(
        pool=pool,
        schema="navigator",
        table_name="form_schemas",
    )
    await storage.initialize()   # DDL only, pool not closed on close()
    await storage.save(form_schema, tenant="epson")
    form = await storage.load("my-form", tenant="epson")

## Classes

- **`PostgresFormStorage(FormStorage)`** — Persist FormSchema objects in a PostgreSQL table using asyncpg.
