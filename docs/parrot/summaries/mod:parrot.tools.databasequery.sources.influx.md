---
type: Wiki Summary
title: parrot.tools.databasequery.sources.influx
id: mod:parrot.tools.databasequery.sources.influx
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: InfluxDB time-series database source for DatabaseToolkit.
relates_to:
- concept: class:parrot.tools.databasequery.sources.influx.InfluxSource
  rel: defines
- concept: mod:parrot.interfaces.database
  rel: references
- concept: mod:parrot.tools.databasequery.base
  rel: references
- concept: mod:parrot.tools.databasequery.sources
  rel: references
---

# `parrot.tools.databasequery.sources.influx`

InfluxDB time-series database source for DatabaseToolkit.

Implements ``AbstractDatabaseSource`` for InfluxDB using the asyncdb ``influx``
driver with Flux query language. Overrides ``validate_query()`` with Flux
pattern-based validation. Discovers schema by listing buckets and field keys.

Part of FEAT-062 — DatabaseToolkit.

## Classes

- **`InfluxSource(AbstractDatabaseSource)`** — InfluxDB time-series database source.
