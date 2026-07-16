---
type: Wiki Summary
title: parrot.observability.bootstrap
id: mod:parrot.observability.bootstrap
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: ensure_observability_bootstrapped — env-driven, idempotent auto-boot.
relates_to:
- concept: func:parrot.observability.bootstrap.ensure_observability_bootstrapped
  rel: defines
- concept: func:parrot.observability.bootstrap.reset_bootstrap_for_tests
  rel: defines
- concept: func:parrot.observability.bootstrap.shutdown_observability
  rel: defines
- concept: func:parrot.observability.bootstrap.shutdown_usage_recording
  rel: defines
- concept: mod:parrot.core.events.lifecycle.global_registry
  rel: references
- concept: mod:parrot.observability.config
  rel: references
- concept: mod:parrot.observability.cost.calculator
  rel: references
- concept: mod:parrot.observability.recorders.factory
  rel: references
- concept: mod:parrot.observability.recorders.subscriber
  rel: references
- concept: mod:parrot.observability.setup
  rel: references
- concept: mod:parrot.observability.traceloop_integration
  rel: references
---

# `parrot.observability.bootstrap`

ensure_observability_bootstrapped — env-driven, idempotent auto-boot.

Called once (lazily, from ``EventEmitterMixin._init_events``) the first time any
bot/client/tool is constructed. When ``OBSERVABILITY_ENABLED=true``, it activates
the usage-recording layer selected by ``OBSERVABILITY_BACKEND`` WITHOUT the user
writing any code:

- ``logging`` (default when enabled and backend unset): structured per-call cost
  logs — zero infra, no OTel SDK import.
- ``prometheus``: lazy ``prometheus_client`` exposition.
- ``otel``: delegates to ``setup_telemetry`` (full OTLP traces + metrics).

Idempotent and near-zero cost when disabled: the very first line is a boolean
check; after the first construction the env is never re-read.

## Functions

- `def ensure_observability_bootstrapped() -> None` — Activate env-driven observability exactly once. Safe to call repeatedly.
- `def shutdown_observability() -> None` — Flush and tear down every active observability path. Idempotent + defensive.
- `def shutdown_usage_recording() -> None` — Unsubscribe the usage subscriber and close recorders. Idempotent.
- `def reset_bootstrap_for_tests() -> None` — Test-only: reset module state so a fresh bootstrap can run.
