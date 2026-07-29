---
type: Wiki Summary
title: parrot.bots.database.toolkits.documentdb
id: mod:parrot.bots.database.toolkits.documentdb
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: DocumentDBToolkit — MongoDB Query Language (MQL) support.
relates_to:
- concept: class:parrot.bots.database.toolkits.documentdb.DocumentDBToolkit
  rel: defines
- concept: mod:parrot.bots.database.models
  rel: references
- concept: mod:parrot.bots.database.toolkits.base
  rel: references
---

# `parrot.bots.database.toolkits.documentdb`

DocumentDBToolkit — MongoDB Query Language (MQL) support.

Inherits directly from ``DatabaseToolkit`` since DocumentDB/MongoDB
uses its own query language, not SQL.

## Classes

- **`DocumentDBToolkit(DatabaseToolkit)`** — DocumentDB/MongoDB toolkit with MQL support.
