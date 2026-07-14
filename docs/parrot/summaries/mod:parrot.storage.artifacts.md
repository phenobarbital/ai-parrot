---
type: Wiki Summary
title: parrot.storage.artifacts
id: mod:parrot.storage.artifacts
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: High-level artifact CRUD operations.
relates_to:
- concept: class:parrot.storage.artifacts.ArtifactStore
  rel: defines
- concept: mod:parrot.storage.backends.base
  rel: references
- concept: mod:parrot.storage.models
  rel: references
- concept: mod:parrot.storage.overflow
  rel: references
---

# `parrot.storage.artifacts`

High-level artifact CRUD operations.

Composes ``ConversationBackend`` (artifacts table) and
``OverflowStore`` to provide a single interface for saving,
loading, listing, updating, and deleting artifacts.

FEAT-116: Refactored to use ConversationBackend ABC and OverflowStore.
Removed the leaky ConversationDynamoDB-specific abstraction (FEAT-116).
See docs/storage-backends.md for backend configuration.

## Classes

- **`ArtifactStore`** — Artifact CRUD operations against the configured storage backend.
