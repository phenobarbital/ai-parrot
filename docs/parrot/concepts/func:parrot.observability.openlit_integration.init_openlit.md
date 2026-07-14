---
type: Concept
title: init_openlit()
id: func:parrot.observability.openlit_integration.init_openlit
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Initialize OpenLIT auto-instrumentation. Idempotent.
---

# init_openlit

```python
def init_openlit(config: ObservabilityConfig) -> None
```

Initialize OpenLIT auto-instrumentation. Idempotent.

On the first call, lazy-imports ``openlit`` and calls ``openlit.init`` with
the OTLP endpoint and application name from *config*. Subsequent calls are
no-ops (the sentinel prevents double-init).

Args:
    config: ``ObservabilityConfig`` instance. ``otlp_endpoint``,
        ``service_name`` and ``openlit_disabled_instrumentors`` are
        forwarded to ``openlit.init``. The skip-list defaults to the
        instrumentors known to break against the installed SDK versions
        (``openai``, ``openai_agents``, ``milvus``, ``fastapi``,
        ``starlette``, ``tornado``) so boot logs stay clean.

Raises:
    ImportError: If ``openlit`` is not installed. Install with:
        ``pip install 'ai-parrot[observability-openlit]'``.
