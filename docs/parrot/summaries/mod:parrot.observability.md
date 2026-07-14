---
type: Wiki Summary
title: parrot.observability
id: mod:parrot.observability
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: parrot.observability — OpenTelemetry + Cost Observability for AI-Parrot.
relates_to:
- concept: mod:parrot.observability.bootstrap
  rel: references
- concept: mod:parrot.observability.config
  rel: references
- concept: mod:parrot.observability.context
  rel: references
- concept: mod:parrot.observability.cost.calculator
  rel: references
- concept: mod:parrot.observability.errors
  rel: references
- concept: mod:parrot.observability.provider
  rel: references
- concept: mod:parrot.observability.recorders
  rel: references
- concept: mod:parrot.observability.setup
  rel: references
- concept: mod:parrot.observability.subscribers.metrics
  rel: references
- concept: mod:parrot.observability.subscribers.trace
  rel: references
- concept: mod:parrot.observability.traceloop_integration
  rel: references
---

# `parrot.observability`

parrot.observability — OpenTelemetry + Cost Observability for AI-Parrot.

FEAT-177. Provides a one-call boot helper ``setup_telemetry(ObservabilityConfig)``
that wires GenAI SemConv-compliant spans, OTel metrics (counters/histograms),
and USD cost tracking against FEAT-176's lifecycle events.

Public surface:
  * ``ObservabilityConfig`` — Pydantic v2 config model (TASK-1228).
  * ``setup_telemetry`` / ``shutdown_telemetry`` — boot helpers (TASK-1235).
  * ``ParrotTelemetryProvider`` — EventProvider bundle (TASK-1233).
  * ``ConfigurationError`` — raised on bad/conflicting config (TASK-1235).
  * ``GenAIOpenTelemetrySubscriber`` — rich span subscriber (TASK-1230).
  * ``MetricsSubscriber`` — counters + histograms subscriber (TASK-1231).
  * ``CostCalculator`` — USD cost calculator (TASK-1232).

Pluggable usage-logging layer (no OpenTelemetry SDK required for the logging
path):
  * ``AbstractLogger`` — the pluggable recorder interface.
  * ``UsageRecord`` — normalized, PII-free per-call record.
  * ``LoggingUsageRecorder`` — zero-infra structured-log backend.
  * ``UsageRecordingSubscriber`` — builds records + fans out to recorders.
  * ``ensure_observability_bootstrapped`` / ``shutdown_usage_recording`` —
    env-driven auto-boot helpers.
  * ``shutdown_observability`` — aggregate flush/teardown for any active backend
    (registered automatically via ``atexit`` on first boot).

OpenLLMetry (Traceloop) backend — a simple, content-rich local/dev tracing path,
mutually exclusive with OpenLIT (the production backend):
  * ``init_traceloop`` / ``setup_traceloop`` / ``shutdown_traceloop`` — activate
    via ``OBSERVABILITY_TRACELOOP=true`` (or ``usage_backend="traceloop"``).

Per-agent attribution (FEAT-228):
  * ``current_agent_name`` — task-local ``ContextVar[Optional[str]]`` holding
    the invoking agent's ``self.name``.
  * ``agent_identity(name)`` — context-manager that binds the active agent name
    for the duration of a bot invocation (token-based; nested-safe).
