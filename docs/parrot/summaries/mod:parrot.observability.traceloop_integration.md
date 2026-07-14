---
type: Wiki Summary
title: parrot.observability.traceloop_integration
id: mod:parrot.observability.traceloop_integration
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: OpenLLMetry (Traceloop) backend — simple, content-rich tracing for local/dev.
relates_to:
- concept: func:parrot.observability.traceloop_integration.init_traceloop
  rel: defines
- concept: func:parrot.observability.traceloop_integration.setup_traceloop
  rel: defines
- concept: func:parrot.observability.traceloop_integration.shutdown_traceloop
  rel: defines
- concept: mod:parrot.core.events.lifecycle.global_registry
  rel: references
- concept: mod:parrot.observability.config
  rel: references
- concept: mod:parrot.observability.cost.calculator
  rel: references
- concept: mod:parrot.observability.provider
  rel: references
- concept: mod:parrot.observability.subscribers.metrics
  rel: references
- concept: mod:parrot.observability.subscribers.trace
  rel: references
---

# `parrot.observability.traceloop_integration`

OpenLLMetry (Traceloop) backend — simple, content-rich tracing for local/dev.

This is the sibling of ``openlit_integration``: a lazy, idempotent wrapper around
``traceloop.sdk.Traceloop.init`` plus a ``setup_traceloop`` helper that wires
AI-Parrot's native span/metric subscribers onto the global provider Traceloop
installs — so a single OTLP pipeline carries BOTH Traceloop's SDK-level spans
(with prompt/completion capture) AND AI-Parrot's agent/tool/client spans + usage
metrics, with no duplicated spans.

Why a separate owner (vs. OpenLIT, which layers on ``setup_telemetry``):
``Traceloop.init`` reuses an existing real ``TracerProvider`` if one is set, else
creates its own and registers it globally (see ``init_tracer_provider`` in
traceloop-sdk). We therefore let Traceloop own the pipeline and attach our
subscribers afterwards via the global provider — running ``setup_telemetry`` too
would add a second exporter and double-export every span.

OpenLIT and Traceloop are mutually exclusive at runtime (the auto-boot disables
OpenLIT when Traceloop is requested). Install with:
``pip install 'ai-parrot[observability,observability-traceloop]'``.

## Functions

- `def init_traceloop(config: ObservabilityConfig) -> None` — Initialize the Traceloop SDK (OpenLLMetry). Idempotent.
- `def setup_traceloop(config: ObservabilityConfig) -> None` — Activate the full ``traceloop`` backend. Idempotent.
- `def shutdown_traceloop() -> None` — Flush Traceloop and unregister native subscribers. Idempotent + defensive.
