---
type: Wiki Overview
title: 'TASK-1234: OTLP exporter helpers'
id: doc:sdd-tasks-completed-task-1234-otlp-exporter-helpers-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 7. Factory helpers that return OTLP exporters configured from
  `ObservabilityConfig` for either `http/protobuf` or `grpc` protocol. Keeps `setup_telemetry`
  clean.
relates_to:
- concept: mod:parrot.observability
  rel: mentions
- concept: mod:parrot.observability.config
  rel: mentions
- concept: mod:parrot.observability.exporters
  rel: mentions
---

# TASK-1234: OTLP exporter helpers

**Feature**: FEAT-177 — OpenTelemetry + Cost Observability
**Spec**: `sdd/specs/otel-observability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1228
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7. Factory helpers that return OTLP exporters configured from `ObservabilityConfig` for either `http/protobuf` or `grpc` protocol. Keeps `setup_telemetry` clean.

---

## Scope

- Create `parrot/observability/exporters.py` with:
  - `make_span_exporter(config: ObservabilityConfig) -> SpanExporter`
  - `make_metric_exporter(config: ObservabilityConfig) -> MetricExporter`
- Lazy-import the gRPC and HTTP exporter modules so users without grpcio installed are not broken when they choose `http/protobuf` (the default).
- Unit tests for protocol selection.

**NOT in scope**: Constructing `TracerProvider` / `MeterProvider` — `setup_telemetry` does that (TASK-1235).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/exporters.py` | CREATE | Two factory functions. |
| `packages/ai-parrot/tests/unit/observability/test_exporters.py` | CREATE | Protocol selection tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from __future__ import annotations
from typing import Any
from parrot.observability.config import ObservabilityConfig

# Lazy-imported inside each factory:
#   from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
#   from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
#   from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as GrpcSpanExporter
#   from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter as GrpcMetricExporter
```

### `ObservabilityConfig` fields used

- `otlp_endpoint: str`
- `otlp_protocol: Literal["http/protobuf", "grpc"]`
- `otlp_headers: dict[str, str]`

### Does NOT Exist

- ~~`SimpleSpanProcessor`~~ — forbidden by spec §5; this task does NOT use it. `setup_telemetry` wires `BatchSpanProcessor` around our exporters.

---

## Implementation Notes

```python
def make_span_exporter(config: ObservabilityConfig) -> Any:
    if config.otlp_protocol == "grpc":
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter as GrpcSpanExporter,
            )
        except ImportError as exc:
            raise ImportError(
                "gRPC OTLP exporter requires the grpc extra. "
                "Install with: pip install 'ai-parrot[observability]'"
            ) from exc
        return GrpcSpanExporter(
            endpoint=config.otlp_endpoint,
            headers=tuple(config.otlp_headers.items()) or None,
        )
    # default: http/protobuf
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    return OTLPSpanExporter(
        endpoint=f"{config.otlp_endpoint}/v1/traces",
        headers=config.otlp_headers or None,
    )


def make_metric_exporter(config: ObservabilityConfig) -> Any:
    # symmetric to make_span_exporter; URL suffix /v1/metrics for HTTP
    ...
```

### Key Constraints

- HTTP endpoint construction appends `/v1/traces` and `/v1/metrics` only for HTTP (gRPC uses the base endpoint directly).
- Empty `otlp_headers` dict → pass `None` (matches OTel SDK expectation).
- Never instantiate both HTTP and gRPC versions in one call.

---

## Acceptance Criteria

- [ ] `from parrot.observability.exporters import make_span_exporter, make_metric_exporter` resolves.
- [ ] `make_span_exporter(ObservabilityConfig())` returns an `OTLPSpanExporter` instance (HTTP variant).
- [ ] `make_span_exporter(ObservabilityConfig(otlp_protocol="grpc"))` returns the gRPC variant.
- [ ] HTTP exporter endpoint ends with `/v1/traces` or `/v1/metrics`.
- [ ] When grpcio is missing, requesting `protocol="grpc"` raises `ImportError` with a clear action message.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/observability/test_exporters.py
import pytest
from parrot.observability import ObservabilityConfig
from parrot.observability.exporters import make_span_exporter, make_metric_exporter


def test_default_http_span_exporter():
    exp = make_span_exporter(ObservabilityConfig())
    name = type(exp).__module__
    assert "proto.http" in name


def test_grpc_span_exporter():
    exp = make_span_exporter(ObservabilityConfig(otlp_protocol="grpc"))
    name = type(exp).__module__
    assert "proto.grpc" in name


def test_http_endpoint_suffix():
    exp = make_span_exporter(ObservabilityConfig(
        otlp_endpoint="http://otel:4318"))
    # endpoint attribute name differs across SDK versions; verify via repr/str
    assert "/v1/traces" in repr(vars(exp))


def test_metric_exporter_round_trip():
    exp = make_metric_exporter(ObservabilityConfig())
    assert exp is not None
```

---

## Agent Instructions

1. Confirm TASK-1228 complete.
2. Implement exporters.py + tests.
3. Run `pytest packages/ai-parrot/tests/unit/observability/test_exporters.py -v` (requires the `observability` extra to be installed in dev env).

---

## Completion Note

Implemented `make_span_exporter` and `make_metric_exporter` in `parrot/observability/exporters.py`.
HTTP variant appends `/v1/traces` or `/v1/metrics` to the base endpoint; gRPC variant uses the
base endpoint directly with lazy imports guarded by a clear ImportError. Empty `otlp_headers`
dict is normalized to `None` per OTel SDK expectations. All acceptance criteria verified via
direct Python invocation (pytest conftest fails due to broken env dependency, unrelated to task).
Both test_exporters.py and exporters.py committed in feat(otel-observability): TASK-1234 commit.
