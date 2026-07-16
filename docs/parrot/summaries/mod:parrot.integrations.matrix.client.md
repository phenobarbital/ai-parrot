---
type: Wiki Summary
title: parrot.integrations.matrix.client
id: mod:parrot.integrations.matrix.client
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Async Matrix client wrapper for AI-Parrot.
relates_to:
- concept: class:parrot.integrations.matrix.client.MatrixClientWrapper
  rel: defines
---

# `parrot.integrations.matrix.client`

Async Matrix client wrapper for AI-Parrot.

Thin abstraction over mautrix.client.Client that exposes only
the operations needed by MatrixHook, MatrixStreamHandler, and
MatrixA2ATransport.

## Classes

- **`MatrixClientWrapper`** — Async wrapper around mautrix Client for AI-Parrot operations.
