---
type: Wiki Summary
title: parrot.tools.databasequery.sources.mongodb
id: mod:parrot.tools.databasequery.sources.mongodb
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: MongoDB database source for DatabaseToolkit.
relates_to:
- concept: class:parrot.tools.databasequery.sources.mongodb.MongoSource
  rel: defines
- concept: mod:parrot.interfaces.database
  rel: references
- concept: mod:parrot.tools.databasequery.base
  rel: references
- concept: mod:parrot.tools.databasequery.sources
  rel: references
---

# `parrot.tools.databasequery.sources.mongodb`

MongoDB database source for DatabaseToolkit.

Implements ``AbstractDatabaseSource`` for MongoDB using the asyncdb ``mongo``
driver. Overrides ``validate_query()`` with JSON-based validation (filter
documents and aggregation pipelines). Discovers schema via collection listing
and ``$sample`` aggregation for field inference.

This is the base class for ``DocumentDBSource`` and ``AtlasSource``.

Part of FEAT-062 — DatabaseToolkit.

## Classes

- **`MongoSource(AbstractDatabaseSource)`** — MongoDB database source.
