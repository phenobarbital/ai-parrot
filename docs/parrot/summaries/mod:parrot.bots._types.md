---
type: Wiki Summary
title: parrot.bots._types
id: mod:parrot.bots._types
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Shared structural types for the ``parrot.bots`` package.
relates_to:
- concept: class:parrot.bots._types.AgentDispatcher
  rel: defines
---

# `parrot.bots._types`

Shared structural types for the ``parrot.bots`` package.

This module is intentionally dependency-free (stdlib ``typing`` only) so it
can be imported by any agent without pulling in heavy machinery, and — most
importantly — without ever importing server-side packages
(``parrot.autonomous`` / ``ai-parrot-server``). Core must not import server.

## Classes

- **`AgentDispatcher(Protocol)`** — Duck-typed async callable that dispatches a named agent.
