---
type: Wiki Entity
title: ConfigurationError
id: class:parrot.observability.errors.ConfigurationError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Raised when ``setup_telemetry`` receives an invalid or conflicting configuration.
---

# ConfigurationError

Defined in [`parrot.observability.errors`](../summaries/mod:parrot.observability.errors.md).

```python
class ConfigurationError(Exception)
```

Raised when ``setup_telemetry`` receives an invalid or conflicting configuration.

Examples:
    - ``setup_telemetry`` is called twice with different ``ObservabilityConfig``
      instances (hash conflict).
    - A forbidden ``SimpleSpanProcessor`` is detected in the span-processor
      pipeline after provider construction.
