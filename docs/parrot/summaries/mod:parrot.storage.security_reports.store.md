---
type: Wiki Summary
title: parrot.storage.security_reports.store
id: mod:parrot.storage.security_reports.store
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: SecurityReportStore Protocol + PostgresS3SecurityReportStore implementation.
relates_to:
- concept: class:parrot.storage.security_reports.store.PostgresS3SecurityReportStore
  rel: defines
- concept: class:parrot.storage.security_reports.store.SecurityReportStore
  rel: defines
- concept: mod:parrot.interfaces.file
  rel: references
- concept: mod:parrot.storage.security_reports.models
  rel: references
---

# `parrot.storage.security_reports.store`

SecurityReportStore Protocol + PostgresS3SecurityReportStore implementation.

The store is the catalog's persistence core:
- Postgres holds metadata (queryable, indexed) via asyncdb.AsyncDB.
- S3 holds content (cheap, large blobs) via FileManagerInterface.

Key design invariants:
1. S3 upload FIRST, Postgres INSERT second (S3-wins, Postgres-reconciled).
2. query() NEVER applies an implicit ``since`` filter — visibility window
   is the caller's responsibility (spec §5 hard requirement).
3. ``delete()`` is reserved for explicit GDPR requests; never called by
   automatic retention paths (spec §1 Goals: compliance retention).
4. bootstrap_schema() is idempotent (all DDL uses IF NOT EXISTS).

## Classes

- **`SecurityReportStore(Protocol)`** — Protocol for the security report catalog persistence layer.
- **`PostgresS3SecurityReportStore`** — Postgres (metadata) + S3/FileManager (content) catalog implementation.
