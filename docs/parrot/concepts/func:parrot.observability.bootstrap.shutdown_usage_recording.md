---
type: Concept
title: shutdown_usage_recording()
id: func:parrot.observability.bootstrap.shutdown_usage_recording
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Unsubscribe the usage subscriber and close recorders. Idempotent.
---

# shutdown_usage_recording

```python
def shutdown_usage_recording() -> None
```

Unsubscribe the usage subscriber and close recorders. Idempotent.

Only affects the lightweight (logging/prometheus) path. The OTel path is
torn down via ``shutdown_telemetry``.
