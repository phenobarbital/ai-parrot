---
type: Concept
title: shutdown_observability()
id: func:parrot.observability.bootstrap.shutdown_observability
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Flush and tear down every active observability path. Idempotent + defensive.
---

# shutdown_observability

```python
def shutdown_observability() -> None
```

Flush and tear down every active observability path. Idempotent + defensive.

Aggregates every shutdown surface so callers need not know which backend is
active: the OTel path (``shutdown_telemetry``), the Traceloop path
(``shutdown_traceloop``), and the lightweight logging/prometheus path
(``shutdown_usage_recording``). Safe to call when observability was never
started; never raises.
