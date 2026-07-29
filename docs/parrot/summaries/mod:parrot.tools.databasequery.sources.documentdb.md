---
type: Wiki Summary
title: parrot.tools.databasequery.sources.documentdb
id: mod:parrot.tools.databasequery.sources.documentdb
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: AWS DocumentDB database source for DatabaseToolkit.
relates_to:
- concept: class:parrot.tools.databasequery.sources.documentdb.DocumentDBSource
  rel: defines
- concept: mod:parrot.interfaces.database
  rel: references
- concept: mod:parrot.tools.databasequery.sources
  rel: references
- concept: mod:parrot.tools.databasequery.sources.mongodb
  rel: references
---

# `parrot.tools.databasequery.sources.documentdb`

AWS DocumentDB database source for DatabaseToolkit.

Extends ``MongoSource`` for AWS DocumentDB, which uses the MongoDB wire protocol
with ``dbtype="documentdb"``. Adds SSL-by-default credential defaults required
for AWS DocumentDB connections.

Inherits ``test_connection()`` from ``MongoSource`` (MongoDB ping command via
the asyncdb mongo driver).

Part of FEAT-062 — DatabaseToolkit.
Part of FEAT-136 — database-toolkit-parity (TASK-933 test_connection inheritance).

## Classes

- **`DocumentDBSource(MongoSource)`** — AWS DocumentDB database source.
