---
type: Wiki Summary
title: parrot.observability.recorders.base
id: mod:parrot.observability.recorders.base
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: AbstractLogger — the pluggable usage-recording interface.
relates_to:
- concept: class:parrot.observability.recorders.base.AbstractLogger
  rel: defines
- concept: mod:parrot.observability.recorders.models
  rel: references
---

# `parrot.observability.recorders.base`

AbstractLogger — the pluggable usage-recording interface.

Every usage backend (logging, Prometheus, …) implements this single async
surface so that swapping backends is a configuration change, not a code change.
``UsageRecordingSubscriber`` builds one ``UsageRecord`` per LLM call and calls
``record`` on each configured backend.

## Classes

- **`AbstractLogger(ABC)`** — Abstract base for pluggable usage/token/cost recorders.
