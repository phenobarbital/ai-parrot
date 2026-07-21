---
type: Wiki Summary
title: parrot.tools.databasequery.sources.atlas
id: mod:parrot.tools.databasequery.sources.atlas
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: MongoDB Atlas database source for DatabaseToolkit.
relates_to:
- concept: class:parrot.tools.databasequery.sources.atlas.AtlasSource
  rel: defines
- concept: mod:parrot.interfaces.database
  rel: references
- concept: mod:parrot.tools.databasequery.sources
  rel: references
- concept: mod:parrot.tools.databasequery.sources.mongodb
  rel: references
---

# `parrot.tools.databasequery.sources.atlas`

MongoDB Atlas database source for DatabaseToolkit.

Extends ``MongoSource`` for MongoDB Atlas cloud service, which uses the
``mongodb+srv://`` connection string format and ``dbtype="atlas"``.

Inherits ``test_connection()`` from ``MongoSource`` (MongoDB ping command).

Part of FEAT-062 — DatabaseToolkit.
Part of FEAT-136 — database-toolkit-parity (G8 credential resolution,
TASK-933 test_connection inheritance).

## Classes

- **`AtlasSource(MongoSource)`** — MongoDB Atlas database source.
