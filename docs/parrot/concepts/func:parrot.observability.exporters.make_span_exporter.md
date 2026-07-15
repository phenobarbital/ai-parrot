---
type: Concept
title: make_span_exporter()
id: func:parrot.observability.exporters.make_span_exporter
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return an OTLP span exporter configured from *config*.
---

# make_span_exporter

```python
def make_span_exporter(config: ObservabilityConfig) -> Any
```

Return an OTLP span exporter configured from *config*.

Args:
    config: ``ObservabilityConfig`` instance providing endpoint, protocol,
        and optional headers.

Returns:
    An ``OTLPSpanExporter`` instance (HTTP or gRPC variant).

Raises:
    ImportError: When ``protocol="grpc"`` is requested but the gRPC
        exporter package is not installed.
