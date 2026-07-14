---
type: Wiki Summary
title: parrot.integrations.matrix.a2a_transport
id: mod:parrot.integrations.matrix.a2a_transport
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Matrix A2A Transport — agent-to-agent communication over Matrix.
relates_to:
- concept: class:parrot.integrations.matrix.a2a_transport.MatrixA2ATransport
  rel: defines
- concept: mod:parrot.integrations.matrix.client
  rel: references
- concept: mod:parrot.integrations.matrix.events
  rel: references
---

# `parrot.integrations.matrix.a2a_transport`

Matrix A2A Transport — agent-to-agent communication over Matrix.

Uses custom m.parrot.* events to implement A2A protocol semantics
on top of Matrix rooms, enabling federated agent communication
with persistent history.

## Classes

- **`MatrixA2ATransport`** — A2A transport layer using Matrix as the message bus.
