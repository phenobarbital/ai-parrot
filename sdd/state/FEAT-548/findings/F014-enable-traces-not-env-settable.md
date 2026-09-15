---
id: F014
query_id: Q006
type: read
intent: Determine whether traces can be turned off from env alone, once the OTLP endpoint moves to Prometheus
executed_at: 2026-09-10T16:40:00Z
parent_id: F006
depth: 2
---

# F014 — `enable_traces` is NOT settable from env; `OBSERVABILITY_SAMPLING=0.0` is the env-only way to silence traces

## Summary

`ObservabilityConfig` declares `enable_traces: bool = True` and
`enable_metrics: bool = True`, and `setup_telemetry` honours both — but
`from_env()` never populates either key. Grepping the whole `from_env` body for
`"enable_traces"` / `"enable_metrics"` returns nothing. They are code-only
fields.

Consequence for a pure env-var move: pointing `OTEL_EXPORTER_OTLP_ENDPOINT` at
Prometheus moves BOTH signals, because traces fall back to `otlp_endpoint` when
`otlp_targets` is empty (F006). Traces would then POST to
`http://localhost:9090/api/v1/otlp/v1/traces`, which Prometheus 2.x does not
serve.

There is, however, an env-only lever that achieves the same end result:
`OBSERVABILITY_SAMPLING=0.0` feeds `TraceIdRatioBased(0.0)`, which marks every
span non-recording. Non-sampled spans never reach the `BatchSpanProcessor`'s
export path, so no trace request is ever issued and no 404 occurs. The
`TracerProvider` is still constructed, but it is inert.

## Citations

- path: `packages/ai-parrot/src/parrot/observability/config.py`
  lines: 132-133
  symbol: `ObservabilityConfig.enable_traces`
  excerpt: |
    enable_traces: bool = True
    enable_metrics: bool = True

- path: `packages/ai-parrot/src/parrot/observability/config.py`
  lines: 347-470
  symbol: `ObservabilityConfig.from_env`
  excerpt: |
    # grep of the full from_env body for "enable_traces" / "enable_metrics":
    # no match — these fields are never read from the environment.
    "sampling_ratio": _as_float(get("OBSERVABILITY_SAMPLING"), defaults.sampling_ratio),

- path: `packages/ai-parrot/src/parrot/observability/setup.py`
  lines: 144-146
  symbol: `setup_telemetry`
  excerpt: |
    tracer_provider = TracerProvider(
        resource=resource,
        sampler=TraceIdRatioBased(config.sampling_ratio),
    )

- path: `packages/ai-parrot/src/parrot/observability/setup.py`
  lines: 243-250
  excerpt: |
    trace_sub = (
        GenAIOpenTelemetrySubscriber(...)
        if config.enable_traces
        else None
    )

## Notes

`OBSERVABILITY_SAMPLING` already exists and is already parsed — this needs no
new variable and no code change. If traces are wanted again later, the same
variable restores them (set back to `1.0`) once a trace-capable endpoint is
configured.
