---
type: Wiki Summary
title: parrot.bots.flows.core.storage.backends.documentdb
id: mod:parrot.bots.flows.core.storage.backends.documentdb
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: DocumentDbResultStorage — default backend wrapping DocumentDb (FEAT-147).
relates_to:
- concept: class:parrot.bots.flows.core.storage.backends.documentdb.DocumentDbResultStorage
  rel: defines
- concept: mod:parrot.bots.flows.core.storage.backends.base
  rel: references
- concept: mod:parrot.interfaces.documentdb
  rel: references
---

# `parrot.bots.flows.core.storage.backends.documentdb`

DocumentDbResultStorage — default backend wrapping DocumentDb (FEAT-147).

Preserves today's behaviour exactly: each ``save()`` opens a fresh
``async with DocumentDb()`` context and calls ``db.write()``.

## Classes

- **`DocumentDbResultStorage(ResultStorage)`** — Default backend — preserves the legacy DocumentDB write path.
