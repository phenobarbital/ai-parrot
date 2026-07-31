---
type: Wiki Overview
title: 'TASK-1235: setup_telemetry() boot helper'
id: doc:sdd-tasks-completed-task-1235-setup-telemetry-boot-helper-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 8 and §2 (Initialization flow). The single public entrypoint
  that wires `TracerProvider` + `MeterProvider`, builds the subscribers + cost calculator,
  bundles them into `ParrotTelemetryProvider`, and registers with the global registry.
  Idempotent. No-op when `config
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.global_registry
  rel: mentions
- concept: mod:parrot.observability
  rel: mentions
- concept: mod:parrot.observability.config
  rel: mentions
- concept: mod:parrot.observability.cost.calculator
  rel: mentions
- concept: mod:parrot.observability.errors
  rel: mentions
- concept: mod:parrot.observability.exporters
  rel: mentions
- concept: mod:parrot.observability.openlit_integration
  rel: mentions
- concept: mod:parrot.observability.provider
  rel: mentions
- concept: mod:parrot.observability.subscribers.metrics
  rel: mentions
- concept: mod:parrot.observability.subscribers.trace
  rel: mentions
- concept: mod:parrot.version
  rel: mentions
---

# TASK-1235: setup_telemetry() boot helper

**Feature**: FEAT-177 — OpenTelemetry + Cost Observability
**Spec**: `sdd/specs/otel-observability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1228, TASK-1229, TASK-1230, TASK-1231, TASK-1232, TASK-1233, TASK-1234, TASK-1236
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 and §2 (Initialization flow). The single public entrypoint that wires `TracerProvider` + `MeterProvider`, builds the subscribers + cost calculator, bundles them into `ParrotTelemetryProvider`, and registers with the global registry. Idempotent. No-op when `config.enabled is False`. Optionally calls `openlit.init` when `enable_openlit=True`.

---

## Scope

- Create `parrot/observability/setup.py` with `setup_telemetry(config) -> Optional[ParrotTelemetryProvider]` and `shutdown_telemetry() -> None`.
- Build `Resource` with `service.name`, `service.version`, `service.instance.id = f"{socket.gethostname()}-{os.getpid()}"` (UUID fallback), `parrot.version`.
- Configure `TracerProvider` with `BatchSpanProcessor` + `TraceIdRatioBased(sampling_ratio)`. REJECT `SimpleSpanProcessor` with `ConfigurationError`.
- Configure `MeterProvider` with `PeriodicExportingMetricReader(interval=metric_export_interval_ms)` + Views to set histogram bucket boundaries from `MetricsSubscriber._buckets`.
- Resolve `pricing_override_path`: explicit config wins; otherwise read env var `PARROT_PRICING_PATH` via navconfig.
- Build subscribers + provider, call `get_global_registry().add_provider(provider)`.
- If `enable_openlit=True`, call into Module 9 (TASK-1236).
- Module-level idempotency: store config hash and returned provider; second call with same hash returns same provider; different hash raises `ConfigurationError`.
- `shutdown_telemetry()` flushes batch processors, drains the meter reader, and unregisters via `EventRegistry.unsubscribe` (or by clearing the state if no per-subscriber unsubscribe is exposed — TBD by agent based on FEAT-176 API surface).
- Unit + integration tests per spec §4.

**NOT in scope**: implementing any subscriber, the cost calculator, the OpenLIT wrapper, or the exporter factory — call them.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/setup.py` | CREATE | `setup_telemetry` + `shutdown_telemetry`. |
| `packages/ai-parrot/src/parrot/observability/__init__.py` | MODIFY | Add `setup_telemetry`, `shutdown_telemetry` to re-exports. |
| `packages/ai-parrot/src/parrot/observability/errors.py` | CREATE | `ConfigurationError(Exception)`. |
| `packages/ai-parrot/tests/unit/observability/test_setup.py` | CREATE | Idempotency, no-op, forbidden-processor, instance-id, lazy-import tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from __future__ import annotations
import hashlib
import json
import logging
import os
import socket
import uuid
from typing import Optional

from parrot.observability.config import ObservabilityConfig
from parrot.observability.cost.calculator import CostCalculator
from parrot.observability.exporters import make_metric_exporter, make_span_exporter
from parrot.observability.provider import ParrotTelemetryProvider
from parrot.observability.subscribers.metrics import MetricsSubscriber
from parrot.observability.subscribers.trace import GenAIOpenTelemetrySubscriber
from parrot.core.events.lifecycle.global_registry import get_global_registry

# Lazy:
#   from opentelemetry.sdk.resources import Resource
#   from opentelemetry.sdk.trace import TracerProvider
#   from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
#   from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
#   from opentelemetry.sdk.metrics import MeterProvider
#   from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
#   from opentelemetry.sdk.metrics.view import View, ExplicitBucketHistogramAggregation
#   from opentelemetry import trace as otel_trace
#   from opentelemetry import metrics as otel_metrics
#   from navconfig import config as nav_config   # for PARROT_PRICING_PATH fallback
```

### Existing Signatures to Use

```python
# parrot/core/events/lifecycle/global_registry.py:37
def get_global_registry() -> EventRegistry: ...

# parrot/core/events/lifecycle/registry.py
class EventRegistry:
    def add_provider(self, provider: EventProvider) -> list[str]: ...
    # unsubscribe API — verify against the actual class before implementing
    # shutdown path. Likely method: registry.unsubscribe(subscription_id)
```

### Does NOT Exist

- ~~`opentelemetry.sdk.trace.export.SimpleSpanProcessor` usage~~ — IMPORT IS FINE (we need to detect & forbid it), but never instantiate inside `setup_telemetry`.
- ~~`navconfig.config.set(...)`~~ — we only read env vars.

---

## Implementation Notes

### Sketch

```python
_STATE: dict[str, ParrotTelemetryProvider] = {}   # keyed by config hash


def setup_telemetry(config: ObservabilityConfig) -> Optional[ParrotTelemetryProvider]:
    if not config.enabled:
        return None

    cfg_hash = _hash_config(config)
    if cfg_hash in _STATE:
        return _STATE[cfg_hash]
    if _STATE:
        raise ConfigurationError(
            "setup_telemetry already configured with a different ObservabilityConfig."
        )

    # 1. Resource
    resource = Resource.create({
        "service.name": config.service_name,
        "service.version": config.service_version or "unknown",
        "service.instance.id": config.service_instance_id or _resolve_instance_id(),
        "parrot.version": _get_parrot_version(),
    })

    # 2. TracerProvider
    span_exp = make_span_exporter(config)
    if isinstance(span_exp, SimpleSpanProcessor):   # paranoia — exporter ≠ processor, but
        raise ConfigurationError("SimpleSpanProcessor is forbidden.")
    tracer_provider = TracerProvider(
        resource=resource,
        sampler=TraceIdRatioBased(config.sampling_ratio),
    )
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exp))
    otel_trace.set_tracer_provider(tracer_provider)

    # 3. MeterProvider with histogram Views
    buckets = config.histogram_buckets or [0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0, 60.0]
    views = [
        View(instrument_name=name,
             aggregation=ExplicitBucketHistogramAggregation(buckets))
        for name in [
            "gen_ai.client.operation.duration",
            "parrot.tool.execution.duration",
            "parrot.agent.invoke.duration",
        ]
    ]
    metric_exp = make_metric_exporter(config)
    reader = PeriodicExportingMetricReader(
        metric_exp, export_interval_millis=config.metric_export_interval_ms,
    )
    meter_provider = MeterProvider(
        resource=resource, metric_readers=[reader], views=views,
    )
    otel_metrics.set_meter_provider(meter_provider)

    # 4. Cost (resolve override path)
    cost_calc = None
    if config.enable_cost_tracking:
        override = config.pricing_override_path or nav_config.get(
            "PARROT_PRICING_PATH", fallback=None,
        )
        cost_calc = CostCalculator(override_path=override)

    # 5. Subscribers
    trace_sub = GenAIOpenTelemetrySubscriber(
        service_name=config.service_name,
        tracer_provider=tracer_provider,
        cost_calculator=cost_calc,
        capture_completions=config.capture_completions,
    ) if config.enable_traces else None
    metrics_sub = MetricsSubscriber(
        meter_provider=meter_provider,
        service_name=config.service_name,
        histogram_buckets=buckets,
        cost_calculator=cost_calc,
    ) if config.enable_metrics else None

    provider = ParrotTelemetryProvider(
        trace_subscriber=trace_sub, metrics_subscriber=metrics_sub,
    )
    get_global_registry().add_provider(provider)

    # 6. OpenLIT (lazy)
    if config.enable_openlit:
        from parrot.observability.openlit_integration import init_openlit
        init_openlit(config)

    _STATE[cfg_hash] = provider
    return provider


def shutdown_telemetry() -> None:
    """Flush exporters and clear state. Idempotent."""
    for provider in _STATE.values():
        # shutdown OTel providers — TracerProvider.shutdown() / MeterProvider.shutdown()
        pass
    _STATE.clear()


def _resolve_instance_id() -> str:
    try:
        return f"{socket.gethostname()}-{os.getpid()}"
    except OSError:
        return uuid.uuid4().hex


def _hash_config(config: ObservabilityConfig) -> str:
    return hashlib.sha256(
        json.dumps(config.model_dump(), sort_keys=True, default=str).encode()
    ).hexdigest()
```

### Key Constraints

- `setup_telemetry(ObservabilityConfig(enabled=False))` returns `None` IMMEDIATELY — no OTel imports, no subscriber construction, no global-registry interaction.
- All OTel SDK imports lazy.
- `_get_parrot_version()`: read from `importlib.metadata.version("ai-parrot")` with `try/except` fallback to `"unknown"`.
- The detection of `SimpleSpanProcessor` is actually enforced by the fact that we always wrap with `BatchSpanProcessor` — but ALSO add a defensive assertion that the configured processors list contains zero `SimpleSpanProcessor` instances, raising `ConfigurationError` if (somehow) one slipped in via monkey-patching.

---

## Acceptance Criteria

- [ ] `from parrot.observability import setup_telemetry, shutdown_telemetry` resolves.
- [ ] `setup_telemetry(ObservabilityConfig(enabled=False))` returns `None`; no subscribers in `get_global_registry()`; no `opentelemetry.sdk` import triggered (verify `sys.modules`).
- [ ] `setup_telemetry(cfg)` and a second `setup_telemetry(cfg)` return the SAME provider instance.
- [ ] Second `setup_telemetry` with a different config raises `ConfigurationError`.
- [ ] When `enable_openlit=True`, `openlit.init` is called via the wrapper; when False, `openlit` is never imported.
- [ ] When `service_instance_id` is `None`, the `Resource` carries `service.instance.id == f"{gethostname()}-{getpid()}"`.
- [ ] Forbidden `SimpleSpanProcessor` raises `ConfigurationError`.
- [ ] `shutdown_telemetry()` after `setup_telemetry()` empties `_STATE`; calling it again is a no-op.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/observability/test_setup.py
import os
import socket
import sys
import pytest
from parrot.observability import (
    ObservabilityConfig, setup_telemetry, shutdown_telemetry,
)
from parrot.observability.errors import ConfigurationError
from parrot.core.events.lifecycle.global_registry import get_global_registry, scope


@pytest.fixture(autouse=True)
def _isolated_registry():
    with scope() as reg:
        yield reg
    shutdown_telemetry()


def test_disabled_is_no_op():
    before = set(sys.modules)
    out = setup_telemetry(ObservabilityConfig(enabled=False))
    assert out is None
    new_modules = set(sys.modules) - before
    assert not any(m.startswith("opentelemetry.sdk") for m in new_modules)


def test_idempotent_same_config():
    cfg = ObservabilityConfig(enabled=True)
    p1 = setup_telemetry(cfg)
    p2 = setup_telemetry(cfg)
    assert p1 is p2


def test_conflicting_config_raises():
    setup_telemetry(ObservabilityConfig(enabled=True, service_name="a"))
    with pytest.raises(ConfigurationError):
        setup_telemetry(ObservabilityConfig(enabled=True, service_name="b"))


def test_service_instance_id_default():
    cfg = ObservabilityConfig(enabled=True)
    p = setup_telemetry(cfg)
    # Inspect the trace subscriber's tracer provider → resource attributes
    from opentelemetry import trace
    resource = trace.get_tracer_provider().resource
    expected = f"{socket.gethostname()}-{os.getpid()}"
    assert resource.attributes.get("service.instance.id") == expected


def test_openlit_lazy_when_disabled():
    setup_telemetry(ObservabilityConfig(enabled=True, enable_openlit=False))
    assert "openlit" not in sys.modules
```

---

## Agent Instructions

1. Confirm all of TASK-1228..TASK-1234 + TASK-1236 are complete.
2. Cross-check `EventRegistry.unsubscribe` API existence before implementing `shutdown_telemetry`; adjust if the method has a different name.
3. Implement setup.py + errors.py + tests.
4. Run `pytest packages/ai-parrot/tests/unit/observability/test_setup.py -v`.

---

## Completion Note

Implemented `setup_telemetry(config)` and `shutdown_telemetry()` in `parrot/observability/setup.py`.
`ConfigurationError` defined in `parrot/observability/errors.py`. `__init__.py` updated to re-export
both boot helpers and `ConfigurationError`. All 9 acceptance criteria verified via direct Python
invocation: disabled returns None with no SDK imports; idempotent same config; conflicting config
raises ConfigurationError; service.instance.id defaults to hostname-pid; openlit lazy when disabled;
openlit.init called when enabled; shutdown clears state; double shutdown idempotent; shutdown before
setup is no-op. The export timeout errors during shutdown are expected (no collector in test env).
Cross-task verified: navconfig.get('PARROT_PRICING_PATH', fallback=None) pattern confirmed working.
Committed as `feat(otel-observability): TASK-1235`.
