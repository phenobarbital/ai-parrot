---
type: Wiki Summary
title: parrot.tools.databasequery.sources.elastic
id: mod:parrot.tools.databasequery.sources.elastic
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Elasticsearch/OpenSearch database source for DatabaseToolkit.
relates_to:
- concept: class:parrot.tools.databasequery.sources.elastic.ElasticSource
  rel: defines
- concept: mod:parrot.interfaces.database
  rel: references
- concept: mod:parrot.tools.databasequery.base
  rel: references
- concept: mod:parrot.tools.databasequery.sources
  rel: references
---

# `parrot.tools.databasequery.sources.elastic`

Elasticsearch/OpenSearch database source for DatabaseToolkit.

Implements ``AbstractDatabaseSource`` for Elasticsearch and OpenSearch using
the asyncdb ``elastic`` driver. Overrides ``validate_query()`` with JSON DSL
validation. Discovers schema via index mappings API.

Single source for both Elasticsearch and OpenSearch — behavior differences
are handled by the asyncdb driver.

Part of FEAT-062 — DatabaseToolkit.

## Classes

- **`ElasticSource(AbstractDatabaseSource)`** — Elasticsearch/OpenSearch database source.
