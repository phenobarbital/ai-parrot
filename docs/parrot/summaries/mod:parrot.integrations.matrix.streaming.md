---
type: Wiki Summary
title: parrot.integrations.matrix.streaming
id: mod:parrot.integrations.matrix.streaming
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Matrix streaming handler — edit-based token streaming.
relates_to:
- concept: class:parrot.integrations.matrix.streaming.MatrixStreamHandler
  rel: defines
- concept: mod:parrot.integrations.matrix.client
  rel: references
---

# `parrot.integrations.matrix.streaming`

Matrix streaming handler — edit-based token streaming.

Uses Matrix's m.replace (message edit) relation to simulate
streaming output by progressively updating a single message
as the LLM generates tokens. The result is visible in any
Matrix client (Element, etc.) and persists in room history.

## Classes

- **`MatrixStreamHandler`** — Handles streaming LLM output to a Matrix room via message edits.
