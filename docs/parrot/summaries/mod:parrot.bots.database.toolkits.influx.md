---
type: Wiki Summary
title: parrot.bots.database.toolkits.influx
id: mod:parrot.bots.database.toolkits.influx
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: InfluxDBToolkit — InfluxDB Flux query support.
relates_to:
- concept: class:parrot.bots.database.toolkits.influx.InfluxDBToolkit
  rel: defines
- concept: mod:parrot.bots.database.models
  rel: references
- concept: mod:parrot.bots.database.toolkits.base
  rel: references
---

# `parrot.bots.database.toolkits.influx`

InfluxDBToolkit — InfluxDB Flux query support.

Inherits directly from ``DatabaseToolkit`` (not ``SQLToolkit``) since
InfluxDB uses Flux query language, not SQL.

## Classes

- **`InfluxDBToolkit(DatabaseToolkit)`** — InfluxDB toolkit with Flux query language support.
