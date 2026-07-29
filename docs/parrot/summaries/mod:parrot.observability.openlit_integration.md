---
type: Wiki Summary
title: parrot.observability.openlit_integration
id: mod:parrot.observability.openlit_integration
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: OpenLIT auto-instrumentation wrapper.
relates_to:
- concept: func:parrot.observability.openlit_integration.init_openlit
  rel: defines
- concept: mod:parrot.observability.config
  rel: references
---

# `parrot.observability.openlit_integration`

OpenLIT auto-instrumentation wrapper.

FEAT-177 TASK-1236.

Provides a lazy, idempotent wrapper around ``openlit.init()``. The module-level
sentinel ``_INITIALIZED`` ensures ``openlit.init`` is called at most once per
process even when ``setup_telemetry`` is invoked multiple times.

OpenLIT is lazy-imported inside ``init_openlit`` so users without the
``observability-openlit`` extra are not broken when they disable OpenLIT (the
default: ``config.enable_openlit=False``).

Parent-span contract: because ``setup_telemetry`` installs the global
``TracerProvider`` *before* calling ``init_openlit``, OpenLIT auto-spans
inherit that provider and are automatically children of the caller's active
span — no extra wiring needed.

Spec §3 Module 9.

## Functions

- `def init_openlit(config: ObservabilityConfig) -> None` — Initialize OpenLIT auto-instrumentation. Idempotent.
