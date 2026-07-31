---
type: Wiki Summary
title: parrot.stores.parents.abstract
id: mod:parrot.stores.parents.abstract
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract base class for parent document searchers.
relates_to:
- concept: class:parrot.stores.parents.abstract.AbstractParentSearcher
  rel: defines
- concept: mod:parrot.stores.models
  rel: references
---

# `parrot.stores.parents.abstract`

Abstract base class for parent document searchers.

This module defines the composable `ParentSearcher` strategy interface that
decouples *where* parent payloads live from *how* the bot retrieves them.

The interface follows the async-first pattern of the project:
- One required `async` method: `fetch`.
- Optional `health_check` that defaults to True.

Implementations MUST NOT raise on individual misses (missing parent IDs are
normal data gaps). Raising is reserved for infrastructure failures such as
connection loss or query errors.

## Classes

- **`AbstractParentSearcher(ABC)`** — Composable strategy for fetching parent documents by ID.
