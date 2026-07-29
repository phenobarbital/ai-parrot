---
type: Wiki Summary
title: parrot.tools.executors.local
id: mod:parrot.tools.executors.local
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: In-process reference executor.
relates_to:
- concept: class:parrot.tools.executors.local.LocalToolExecutor
  rel: defines
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot.tools.executors.abstract
  rel: references
- concept: mod:parrot.tools.executors.runner
  rel: references
---

# `parrot.tools.executors.local`

In-process reference executor.

Mostly exists so tests can exercise the executor-dispatch path without
needing a Kubernetes cluster or a Qworker instance. The same code that
runs in the ``parrot-tools`` worker image is reused here verbatim so
behaviour stays consistent across runtimes.

## Classes

- **`LocalToolExecutor(AbstractToolExecutor)`** — Executor that runs the tool in the current Python process.
