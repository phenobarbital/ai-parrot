---
type: Wiki Summary
title: parrot.tools.executors.qworker
id: mod:parrot.tools.executors.qworker
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Qworker-backed remote tool executor.
relates_to:
- concept: class:parrot.tools.executors.qworker.QworkerToolExecutor
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot.tools.executors.abstract
  rel: references
---

# `parrot.tools.executors.qworker`

Qworker-backed remote tool executor.

Two transports are supported, picked at construction:

* ``transport="http"`` (default) — submits the envelope to a Qworker
  HTTP endpoint via ``Qclient.run()`` when the optional ``qworker`` /
  ``qclient`` package is installed, otherwise via an aiohttp client
  that follows the same conventions used elsewhere in the repo
  (``parrot/integrations/telegram/auth.py`` and
  ``parrot/interfaces/flowtask.py``).
* ``transport="redis"`` — publishes the envelope to a Redis Stream
  (``parrot:tool_tasks``) and blocks reading from a result stream
  (``parrot:tool_results``). Mirrors the pattern in
  ``parrot/services/client.py``.

The two paths are intentionally implemented in one class because they
share the envelope, the timeout semantics, and the ToolResult parsing —
only the wire details differ.

## Classes

- **`QworkerToolExecutor(AbstractToolExecutor)`** — Dispatch tool execution to the Qworker service.
