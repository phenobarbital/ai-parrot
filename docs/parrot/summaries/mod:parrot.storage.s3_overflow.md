---
type: Wiki Summary
title: parrot.storage.s3_overflow
id: mod:parrot.storage.s3_overflow
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: S3 Overflow Manager — backward-compatible subclass of OverflowStore.
relates_to:
- concept: class:parrot.storage.s3_overflow.S3OverflowManager
  rel: defines
- concept: mod:parrot.interfaces.file.s3
  rel: references
- concept: mod:parrot.storage.overflow
  rel: references
---

# `parrot.storage.s3_overflow`

S3 Overflow Manager — backward-compatible subclass of OverflowStore.

This module preserves the original ``S3OverflowManager`` public name for
callers that imported it directly in FEAT-103. New code should use
``OverflowStore`` from ``parrot.storage.overflow`` and pass any
``FileManagerInterface`` implementation.

FEAT-116: dynamodb-fallback-redis — Module 2 (OverflowStore generalization).

## Classes

- **`S3OverflowManager(OverflowStore)`** — Back-compat subclass: OverflowStore bound to S3FileManager.
