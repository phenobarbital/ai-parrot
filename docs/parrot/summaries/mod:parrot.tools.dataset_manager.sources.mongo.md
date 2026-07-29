---
type: Wiki Summary
title: parrot.tools.dataset_manager.sources.mongo
id: mod:parrot.tools.dataset_manager.sources.mongo
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: MongoSource — DataSource subclass for MongoDB/DocumentDB collections.
relates_to:
- concept: class:parrot.tools.dataset_manager.sources.mongo.MongoSource
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.base
  rel: references
---

# `parrot.tools.dataset_manager.sources.mongo`

MongoSource — DataSource subclass for MongoDB/DocumentDB collections.

Read-only. Every fetch() call MUST include a ``filter`` dict parameter — no
full-collection scans are allowed. A ``projection`` dict is also required to
limit returned fields.

On registration, prefetch_schema() runs a find_one() on the collection to
infer field names and types from a single document (excluding the internal
``_id`` field).

Credential resolution supports either a DSN (MongoDB connection string) or a
credentials dict with host/port/user/password/database keys.

## Classes

- **`MongoSource(DataSource)`** — DataSource for MongoDB/DocumentDB collections via asyncdb's mongo driver.
