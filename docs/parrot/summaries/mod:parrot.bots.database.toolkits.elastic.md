---
type: Wiki Summary
title: parrot.bots.database.toolkits.elastic
id: mod:parrot.bots.database.toolkits.elastic
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: ElasticToolkit — Elasticsearch DSL query support.
relates_to:
- concept: class:parrot.bots.database.toolkits.elastic.ElasticToolkit
  rel: defines
- concept: mod:parrot.bots.database.models
  rel: references
- concept: mod:parrot.bots.database.toolkits.base
  rel: references
---

# `parrot.bots.database.toolkits.elastic`

ElasticToolkit — Elasticsearch DSL query support.

Inherits directly from ``DatabaseToolkit`` since Elasticsearch uses
its own DSL, not SQL.

## Classes

- **`ElasticToolkit(DatabaseToolkit)`** — Elasticsearch toolkit with DSL query support.
