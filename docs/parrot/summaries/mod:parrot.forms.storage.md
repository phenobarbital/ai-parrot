---
type: Wiki Summary
title: parrot.forms.storage
id: mod:parrot.forms.storage
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: PostgreSQL Form Storage for the forms abstraction layer.
relates_to:
- concept: class:parrot.forms.storage.PostgresFormStorage
  rel: defines
- concept: mod:parrot.forms.registry
  rel: references
- concept: mod:parrot.forms.schema
  rel: references
- concept: mod:parrot.forms.style
  rel: references
---

# `parrot.forms.storage`

PostgreSQL Form Storage for the forms abstraction layer.

Implements the FormStorage ABC using asyncpg for PostgreSQL persistence.
Forms are stored as JSONB, supporting versioning and UPSERT operations.

Table: form_schemas
- id: UUID primary key
- form_id: VARCHAR UNIQUE per version
- version: VARCHAR
- schema_json: JSONB (serialized FormSchema)
- style_json: JSONB (serialized StyleSchema, optional)
- created_at, updated_at: TIMESTAMPTZ
- created_by: VARCHAR (optional metadata)

Usage (self-managed pool — recommended):
    storage = PostgresFormStorage(dsn="postgresql://user:pw@host/db")
    await storage.initialize()   # creates pool + DDL
    await storage.save(form_schema)
    await storage.close()        # closes pool

Usage (externally-managed pool — backward compatible):
    pool = await asyncpg.create_pool(dsn="postgresql://...")
    storage = PostgresFormStorage(pool=pool)
    await storage.initialize()
    await storage.save(form_schema)
    form = await storage.load("my-form")

## Classes

- **`PostgresFormStorage(FormStorage)`** — Persist FormSchema objects in a PostgreSQL table using asyncpg.
