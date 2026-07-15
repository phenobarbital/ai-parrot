---
type: Concept
title: setup_traceloop()
id: func:parrot.observability.traceloop_integration.setup_traceloop
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Activate the full ``traceloop`` backend. Idempotent.
---

# setup_traceloop

```python
def setup_traceloop(config: ObservabilityConfig) -> None
```

Activate the full ``traceloop`` backend. Idempotent.

1. ``init_traceloop`` — Traceloop owns the OTLP trace pipeline + LLM SDK
   auto-instrumentation (content per the PII gate).
2. Register AI-Parrot's native subscribers (``GenAIOpenTelemetrySubscriber``
   and, when ``enable_metrics``, ``MetricsSubscriber``) on the GLOBAL provider
   Traceloop installed, so agent/tool/client spans and usage/cost metrics flow
   through the same single pipeline — no duplicate export.

Args:
    config: ``ObservabilityConfig`` with ``usage_backend == "traceloop"``.
