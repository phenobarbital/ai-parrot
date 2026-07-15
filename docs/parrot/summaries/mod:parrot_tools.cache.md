---
type: Wiki Summary
title: parrot_tools.cache
id: mod:parrot_tools.cache
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Redis-based caching for Tool and Toolkit API responses.
relates_to:
- concept: class:parrot_tools.cache.ToolCache
  rel: defines
- concept: mod:parrot.conf
  rel: references
---

# `parrot_tools.cache`

Redis-based caching for Tool and Toolkit API responses.

Provides a lightweight cache layer that can be composed into any tool
or toolkit to avoid redundant API calls within a configurable TTL.

## Classes

- **`ToolCache`** — Redis-backed cache for tool/toolkit API responses.
