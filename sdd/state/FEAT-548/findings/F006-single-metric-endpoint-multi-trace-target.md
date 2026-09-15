---
id: F006
query_id: Q018
type: read
intent: Determine whether metrics are pushed via OTLP or pulled via a /metrics scrape endpoint, and how endpoints are composed
executed_at: 2026-09-10T16:15:00Z
parent_id: F005
depth: 1
---

# F006 — Metrics are PUSHed to exactly one OTLP endpoint; traces can fan out to many

## Summary

The `otel` backend is push-only: a `PeriodicExportingMetricReader` wrapping an
`OTLPMetricExporter`. The exporters append the signal path themselves —
`{otlp_endpoint}/v1/metrics` and `{otlp_endpoint}/v1/traces` — so
`OTEL_EXPORTER_OTLP_ENDPOINT` must be a base URL.

Crucially the two signals are wired asymmetrically:
* **Traces** use `config.otlp_targets` when set, and fall back to a
  single implicit target built from `otlp_endpoint` when empty.
* **Metrics** always use `config.otlp_endpoint` alone —
  `make_metric_exporter(config)` never consults `otlp_targets`.

So `OTLP_TARGETS` can redirect traces away from wherever metrics go. A pull
(`/metrics` scrape) model exists ONLY on the separate non-OTel
`PrometheusUsageRecorder` path (`OBSERVABILITY_BACKEND=prometheus`), which
starts a `prometheus_client` HTTP server on port 9464.

## Citations

- path: `packages/ai-parrot/src/parrot/observability/exporters.py`
  lines: 150-154
  symbol: `make_metric_exporter`
  excerpt: |
    endpoint = f"{config.otlp_endpoint.rstrip('/')}/v1/metrics"
    headers = config.otlp_headers or None
    return OTLPMetricExporter(endpoint=endpoint, headers=headers)

- path: `packages/ai-parrot/src/parrot/observability/exporters.py`
  lines: 112-114
  symbol: `make_span_exporter`
  excerpt: |
    endpoint = f"{config.otlp_endpoint.rstrip('/')}/v1/traces"

- path: `packages/ai-parrot/src/parrot/observability/setup.py`
  lines: 133-152
  symbol: `setup_telemetry`
  excerpt: |
    targets: list[OtlpTarget] = config.otlp_targets or [
        OtlpTarget(name="default", endpoint=config.otlp_endpoint,
                   headers=config.otlp_headers)
    ]
    span_exporters = make_span_exporters(targets, protocol=config.otlp_protocol)
    for target, exporter in zip(targets, span_exporters):
        tracer_provider.add_span_processor(BatchSpanProcessor(exporter))

- path: `packages/ai-parrot/src/parrot/observability/setup.py`
  lines: 199-208
  excerpt: |
    metric_exporter = make_metric_exporter(config)
    reader = PeriodicExportingMetricReader(metric_exporter,
        export_interval_millis=config.metric_export_interval_ms)

- path: `packages/ai-parrot/src/parrot/observability/recorders/prometheus_recorder.py`
  lines: 44-80, 116-129
  symbol: `PrometheusUsageRecorder`

## Notes

This asymmetry is the crux of the wiring decision: Prometheus 2.x accepts OTLP
**metrics** at `/api/v1/otlp/v1/metrics` but has no trace endpoint, so pointing
`otlp_endpoint` at Prometheus without also setting `OTLP_TARGETS` would leave
every trace export POSTing to a 404.
