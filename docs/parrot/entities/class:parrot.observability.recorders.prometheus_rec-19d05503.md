---
type: Wiki Entity
title: PrometheusUsageRecorder
id: class:parrot.observability.recorders.prometheus_recorder.PrometheusUsageRecorder
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Record usage as Prometheus counters/histograms exposed over HTTP.
relates_to:
- concept: class:parrot.observability.recorders.base.AbstractLogger
  rel: extends
---

# PrometheusUsageRecorder

Defined in [`parrot.observability.recorders.prometheus_recorder`](../summaries/mod:parrot.observability.recorders.prometheus_recorder.md).

```python
class PrometheusUsageRecorder(AbstractLogger)
```

Record usage as Prometheus counters/histograms exposed over HTTP.

Args:
    port: Exposition HTTP server port (default ``9464``).
    addr: Bind address (default ``"0.0.0.0"``).
    start_server: When ``True`` (default), start the exposition server.
        Pass ``False`` in tests that scrape the default registry directly.

## Methods

- `async def record(self, record: UsageRecord) -> None` — Update Prometheus instruments from *record* (no network in hot path).
