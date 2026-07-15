---
type: Wiki Summary
title: parrot.memory.episodic.backends.faiss
id: mod:parrot.memory.episodic.backends.faiss
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: FAISS backend for episodic memory storage (local development).
relates_to:
- concept: class:parrot.memory.episodic.backends.faiss.FAISSBackend
  rel: defines
- concept: mod:parrot.memory.episodic.models
  rel: references
- concept: mod:parrot.utils.faiss_logging
  rel: references
---

# `parrot.memory.episodic.backends.faiss`

FAISS backend for episodic memory storage (local development).

In-memory FAISS index + dict storage with optional disk persistence.
Namespace filters are applied post-search since FAISS has no SQL.

## Classes

- **`FAISSBackend`** — FAISS-based backend for local development without PostgreSQL.
