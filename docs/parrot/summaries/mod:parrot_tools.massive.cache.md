---
type: Wiki Summary
title: parrot_tools.massive.cache
id: mod:parrot_tools.massive.cache
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Cache layer for MassiveToolkit with per-endpoint TTLs.
relates_to:
- concept: class:parrot_tools.massive.cache.MassiveCache
  rel: defines
- concept: mod:parrot_tools.cache
  rel: references
---

# `parrot_tools.massive.cache`

Cache layer for MassiveToolkit with per-endpoint TTLs.

Different endpoints have different data freshness requirements:
- Options Greeks change tick-by-tick (15 min TTL for decision cadence)
- Short Interest updates bi-monthly (12 hour TTL)
- Short Volume updates daily (6 hour TTL)
- Earnings data is quarterly (24 hour TTL)
- Analyst Ratings are sporadic (4 hour TTL)

## Classes

- **`MassiveCache`** — Cache layer for MassiveToolkit with per-endpoint TTLs.
