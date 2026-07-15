---
type: Concept
title: init_traceloop()
id: func:parrot.observability.traceloop_integration.init_traceloop
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Initialize the Traceloop SDK (OpenLLMetry). Idempotent.
---

# init_traceloop

```python
def init_traceloop(config: ObservabilityConfig) -> None
```

Initialize the Traceloop SDK (OpenLLMetry). Idempotent.

Sets ``TRACELOOP_TRACE_CONTENT`` from the PII-gate flags BEFORE init (the
instrumentations read it at import/instrument time), then lazy-imports
``traceloop.sdk`` and calls ``Traceloop.init`` pointing at ``otlp_endpoint``.
Subsequent calls are no-ops.

Args:
    config: ``ObservabilityConfig``. ``service_name`` → ``app_name``,
        ``otlp_endpoint`` → ``api_endpoint``; ``capture_prompts`` /
        ``capture_completions`` gate prompt/completion capture.

Raises:
    ImportError: If ``traceloop-sdk`` is not installed. Install with:
        ``pip install 'ai-parrot[observability-traceloop]'``.
