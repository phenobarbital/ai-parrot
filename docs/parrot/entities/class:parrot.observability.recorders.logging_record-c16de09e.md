---
type: Wiki Entity
title: LoggingUsageRecorder
id: class:parrot.observability.recorders.logging_recorder.LoggingUsageRecorder
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Record usage by emitting one structured log line per LLM call.
relates_to:
- concept: class:parrot.observability.recorders.base.AbstractLogger
  rel: extends
---

# LoggingUsageRecorder

Defined in [`parrot.observability.recorders.logging_recorder`](../summaries/mod:parrot.observability.recorders.logging_recorder.md).

```python
class LoggingUsageRecorder(AbstractLogger)
```

Record usage by emitting one structured log line per LLM call.

Args:
    level: Logging level for the per-call line (default ``logging.INFO``).
    logger_name: Logger to write to (default ``"parrot.usage"``).

## Methods

- `async def record(self, record: UsageRecord) -> None` — Emit a single line summarising *record*.
