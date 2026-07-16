---
type: Wiki Summary
title: parrot.storage.overflow
id: mod:parrot.storage.overflow
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Generic artifact overflow store backed by any FileManagerInterface.
relates_to:
- concept: class:parrot.storage.overflow.OverflowStore
  rel: defines
- concept: mod:parrot.interfaces.file.abstract
  rel: references
---

# `parrot.storage.overflow`

Generic artifact overflow store backed by any FileManagerInterface.

Transparently offloads artifact definitions that exceed the inline threshold
(200 KB) to any FileManagerInterface implementation (S3, GCS, Local, Temp).
On retrieval the reference is resolved back to the original dict.

FEAT-116: dynamodb-fallback-redis — Module 2 (OverflowStore generalization).
See docs/storage-backends.md for overflow store configuration.

## Classes

- **`OverflowStore`** — Generic artifact overflow store backed by any FileManagerInterface.
