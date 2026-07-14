---
type: Concept
title: shutdown_telemetry()
id: func:parrot.observability.setup.shutdown_telemetry
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Flush all exporters and clear the setup state. Idempotent.
---

# shutdown_telemetry

```python
def shutdown_telemetry() -> None
```

Flush all exporters and clear the setup state. Idempotent.

Calls ``TracerProvider.shutdown()`` (which flushes ``BatchSpanProcessor``)
and ``MeterProvider.shutdown()`` (which flushes
``PeriodicExportingMetricReader``). Then unregisters all subscriptions from
the global event registry and clears the module-level cache so
``setup_telemetry`` can be called again.

This function is safe to call when ``setup_telemetry`` was never called, or
after a previous ``shutdown_telemetry`` — it is fully idempotent.

Note:
    OpenLIT cannot be safely re-initialized after shutdown. If
    ``setup_telemetry(enable_openlit=True)`` is called again after
    ``shutdown_telemetry()``, the OpenLIT instrumentation will not be
    re-applied. Use ``openlit_integration._reset_for_tests()`` only in
    test contexts.
