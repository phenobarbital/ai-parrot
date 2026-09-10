---
id: F001
query_id: Q001
type: grep
intent: Locate the parrot observability/telemetry package and its OTEL entrypoints
executed_at: 2026-09-10T16:10:00Z
parent_id: null
depth: 0
---

# F001 — The OTEL observability layer lives in core `parrot.observability`

## Summary

The whole telemetry stack is one package in the core distribution:
`packages/ai-parrot/src/parrot/observability/`. It is event-driven — it does not
wrap client SDKs; it subscribes to the FEAT-176 lifecycle event bus. `setup.py`
builds a `TracerProvider` + `MeterProvider` and registers two subscribers
(`subscribers/trace.py`, `subscribers/metrics.py`). There is also a parallel,
non-OTel "usage recorder" path under `recorders/`. Both a `build/lib.../` copy
and a `__pycache__` tree exist and must be ignored — the source of truth is
`src/parrot/observability/`.

## Citations

- path: `packages/ai-parrot/src/parrot/observability/setup.py`
  symbol: `setup_telemetry`
  lines: 118-275
  excerpt: |
    tracer_provider = TracerProvider(resource=resource, sampler=TraceIdRatioBased(...))
    ...
    reader = PeriodicExportingMetricReader(metric_exporter,
        export_interval_millis=config.metric_export_interval_ms)
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader], views=views)

- path: `packages/ai-parrot/src/parrot/observability/config.py`
  symbol: `ObservabilityConfig`, `ObservabilityConfig.from_env`

- path: `packages/ai-parrot/src/parrot/observability/exporters.py`
  symbol: `make_metric_exporter`, `make_span_exporters`

- path: `packages/ai-parrot/src/parrot/observability/subscribers/metrics.py`
  symbol: `MetricsSubscriber`

- path: `packages/ai-parrot/src/parrot/observability/subscribers/trace.py`
  symbol: `GenAIOpenTelemetrySubscriber`

- path: `packages/ai-parrot/src/parrot/observability/recorders/prometheus_recorder.py`
  symbol: `PrometheusUsageRecorder`

- path: `packages/ai-parrot/src/parrot/observability/cost/calculator.py`
  symbol: `CostCalculator`

## Notes

Pricing tables are bundled JSON per provider under
`observability/cost/pricing/{anthropic,openai,google,groq,nvidia,huggingface}.json`,
overridable via `PARROT_PRICING_PATH`.
