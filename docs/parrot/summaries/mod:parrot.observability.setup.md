---
type: Wiki Summary
title: parrot.observability.setup
id: mod:parrot.observability.setup
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: setup_telemetry() and shutdown_telemetry() — one-call observability boot
  helpers.
relates_to:
- concept: func:parrot.observability.setup.setup_telemetry
  rel: defines
- concept: func:parrot.observability.setup.shutdown_telemetry
  rel: defines
- concept: mod:parrot.core.events.lifecycle.global_registry
  rel: references
- concept: mod:parrot.observability.config
  rel: references
- concept: mod:parrot.observability.cost.calculator
  rel: references
- concept: mod:parrot.observability.errors
  rel: references
- concept: mod:parrot.observability.exporters
  rel: references
- concept: mod:parrot.observability.openlit_integration
  rel: references
- concept: mod:parrot.observability.provider
  rel: references
- concept: mod:parrot.observability.subscribers.metrics
  rel: references
- concept: mod:parrot.observability.subscribers.trace
  rel: references
---

# `parrot.observability.setup`

setup_telemetry() and shutdown_telemetry() — one-call observability boot helpers.

FEAT-177 TASK-1235.

``setup_telemetry(config)`` is the single public entrypoint that:

1. Builds an OTel ``Resource`` (service.name, service.version, service.instance.id,
   parrot.version).
2. Configures a ``TracerProvider`` with ``BatchSpanProcessor`` + ``TraceIdRatioBased``
   sampler and registers it globally.
3. Configures a ``MeterProvider`` with ``PeriodicExportingMetricReader`` + histogram
   ``View`` objects for LLM-optimised bucket boundaries, and registers it globally.
4. Optionally builds a ``CostCalculator`` (respects ``PARROT_PRICING_PATH`` env var).
5. Constructs ``GenAIOpenTelemetrySubscriber`` and/or ``MetricsSubscriber``.
6. Bundles them into ``ParrotTelemetryProvider`` and calls
   ``get_global_registry().add_provider(provider)``.
7. Optionally calls ``openlit.init`` via the TASK-1236 wrapper.

Idempotent: same ``config`` → same provider returned; different ``config`` →
``ConfigurationError``.  ``config.enabled=False`` → immediate ``None`` return with
zero OTel SDK imports.

Spec §3 Module 8, §2 Initialization flow.

## Functions

- `def setup_telemetry(config: ObservabilityConfig) -> Optional[ParrotTelemetryProvider]` — Configure OpenTelemetry + cost observability and wire to the global registry.
- `def shutdown_telemetry() -> None` — Flush all exporters and clear the setup state. Idempotent.
