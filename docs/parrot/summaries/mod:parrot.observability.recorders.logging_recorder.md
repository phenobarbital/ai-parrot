---
type: Wiki Summary
title: parrot.observability.recorders.logging_recorder
id: mod:parrot.observability.recorders.logging_recorder
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: LoggingUsageRecorder — zero-infra usage backend that logs one line per call.
relates_to:
- concept: class:parrot.observability.recorders.logging_recorder.LoggingUsageRecorder
  rel: defines
- concept: mod:parrot.observability.recorders.base
  rel: references
- concept: mod:parrot.observability.recorders.models
  rel: references
---

# `parrot.observability.recorders.logging_recorder`

LoggingUsageRecorder — zero-infra usage backend that logs one line per call.

The default, lowest-overhead backend: no network, no extra dependencies (stdlib
``logging`` only). Emits a single structured line per LLM call to a dedicated
logger (``parrot.usage`` by default) carrying provider, model, token counts,
estimated cost, duration, and the process-cumulative cost.

## Classes

- **`LoggingUsageRecorder(AbstractLogger)`** — Record usage by emitting one structured log line per LLM call.
