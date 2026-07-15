---
type: Wiki Summary
title: parrot.integrations.matrix
id: mod:parrot.integrations.matrix
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Matrix protocol integration for AI-Parrot.
relates_to:
- concept: mod:parrot.integrations
  rel: references
- concept: mod:parrot.integrations.models
  rel: references
---

# `parrot.integrations.matrix`

Matrix protocol integration for AI-Parrot.

Provides Matrix-based communication for agents via mautrix-python:
- MatrixClientWrapper: async client wrapper
- MatrixStreamHandler: edit-based streaming
- MatrixA2ATransport: A2A over Matrix events
- MatrixAppService: Application Service with virtual MXIDs
- Custom m.parrot.* event types
- MatrixCrewTransport: multi-agent crew (FEAT-044)
