---
type: Wiki Summary
title: parrot.interfaces.database
id: mod:parrot.interfaces.database
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: DB (asyncdb) Extension.
relates_to:
- concept: class:parrot.interfaces.database.DBInterface
  rel: defines
- concept: func:parrot.interfaces.database.get_default_credentials
  rel: defines
- concept: mod:parrot._imports
  rel: references
---

# `parrot.interfaces.database`

DB (asyncdb) Extension.

Async database interface for relational databases using asyncdb.
Supports PostgreSQL (pg) and BigQuery with driver-aware SQL generation,
prepared statement caching, and object serialization (datamodel / pydantic).

## Classes

- **`DBInterface`** — Interface for relational database operations using AsyncDB.

## Functions

- `def get_default_credentials(driver: str) -> dict[str, Any]` — Return default credentials for a database driver from environment variables.
