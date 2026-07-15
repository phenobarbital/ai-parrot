---
type: Concept
title: setup_telemetry()
id: func:parrot.observability.setup.setup_telemetry
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configure OpenTelemetry + cost observability and wire to the global registry.
---

# setup_telemetry

```python
def setup_telemetry(config: ObservabilityConfig) -> Optional[ParrotTelemetryProvider]
```

Configure OpenTelemetry + cost observability and wire to the global registry.

Args:
    config: ``ObservabilityConfig`` controlling every aspect of the stack.

Returns:
    The ``ParrotTelemetryProvider`` registered with the global event registry,
    or ``None`` when ``config.enabled is False``.

Raises:
    ConfigurationError: When called a second time with a *different* config than
        the first call (hash mismatch). Also raised if a ``SimpleSpanProcessor``
        is detected in the constructed ``TracerProvider``'s processor chain.
    ImportError: When ``config.enable_openlit=True`` but the
        ``observability-openlit`` extra is not installed.
