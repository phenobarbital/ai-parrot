---
type: Concept
title: build_recorders_from_config()
id: func:parrot.observability.recorders.factory.build_recorders_from_config
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return the recorder backends for ``config.usage_backend``.
---

# build_recorders_from_config

```python
def build_recorders_from_config(config: 'ObservabilityConfig') -> 'list[AbstractLogger]'
```

Return the recorder backends for ``config.usage_backend``.

Only the lightweight (non-OTel) backends are built here: ``"logging"`` and
``"prometheus"``. The ``"otel"`` and ``"none"`` backends are handled by the
bootstrap (delegate to ``setup_telemetry`` / no-op respectively) and yield no
recorders.

Args:
    config: The observability configuration.

Returns:
    A list of ``AbstractLogger`` instances (possibly empty).
