---
type: Wiki Summary
title: parrot.observability.exporters
id: mod:parrot.observability.exporters
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: OTLP exporter factory helpers.
relates_to:
- concept: func:parrot.observability.exporters.make_metric_exporter
  rel: defines
- concept: func:parrot.observability.exporters.make_span_exporter
  rel: defines
- concept: mod:parrot.observability.config
  rel: references
---

# `parrot.observability.exporters`

OTLP exporter factory helpers.

FEAT-177 TASK-1234.

Factory functions returning OTLP span and metric exporters configured from
``ObservabilityConfig``. Supports both ``http/protobuf`` (default) and
``grpc`` protocols. gRPC exporters are lazy-imported so users without
``grpcio`` installed are not broken when they choose the HTTP default.

Spec §3 Module 7.

## Functions

- `def make_span_exporter(config: ObservabilityConfig) -> Any` — Return an OTLP span exporter configured from *config*.
- `def make_metric_exporter(config: ObservabilityConfig) -> Any` — Return an OTLP metric exporter configured from *config*.
