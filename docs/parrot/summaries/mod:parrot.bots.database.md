---
type: Wiki Summary
title: parrot.bots.database
id: mod:parrot.bots.database
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: parrot.bots.database — Unified database agent with multi-toolkit architecture.
relates_to:
- concept: mod:parrot.bots
  rel: references
- concept: mod:parrot.bots.agent
  rel: references
---

# `parrot.bots.database`

parrot.bots.database — Unified database agent with multi-toolkit architecture.

Public API:
    - ``DatabaseAgent`` — main agent class
    - ``DatabaseToolkit``, ``SQLToolkit``, ``PostgresToolkit``, etc. — toolkits
    - ``CacheManager``, ``CachePartition``, ``CachePartitionConfig`` — caching
    - All models from ``models.py`` remain unchanged
