---
id: F005
query_id: Q006
type: read
intent: Find where those env vars are read (navconfig settings) to know the authoritative variable names
executed_at: 2026-09-10T16:14:00Z
parent_id: F004
depth: 1
---

# F005 — `ObservabilityConfig.from_env()` is the authoritative env-var contract

## Summary

`from_env()` reads through navconfig (falling back to `os.environ`) and is the
single place where variable names are defined. `OTEL_EXPORTER_OTLP_ENDPOINT` is
read as a **base URL** (no `/v1/...` suffix). `OTLP_TARGETS` is a JSON list of
`{name, endpoint, headers}` added by FEAT-462. `OBSERVABILITY_BACKEND` selects
the usage backend from `none|logging|prometheus|otel|traceloop`.

Recognised variables: `OBSERVABILITY_ENABLED`, `OBSERVABILITY_BACKEND`,
`OBSERVABILITY_SERVICE_NAME`, `OBSERVABILITY_COST`, `OBSERVABILITY_LOG_LEVEL`,
`OBSERVABILITY_SAMPLING`, `OBSERVABILITY_OPENLIT` (deprecated),
`OBSERVABILITY_OPENLIT_DISABLE`, `OBSERVABILITY_OPENLIT_LOG_LEVEL`,
`OBSERVABILITY_OPENLIT_DISABLE_METRICS`, `OBSERVABILITY_TRACELOOP` (deprecated),
`OBSERVABILITY_CAPTURE_CONTENT`, `OTEL_EXPORTER_OTLP_ENDPOINT`,
`OBSERVABILITY_PROM_PORT`, `OBSERVABILITY_PROM_ADDR`, `PARROT_PRICING_PATH`,
`OTLP_TARGETS`, `OBSERVABILITY_OPENLIT_RECORDER`,
`OBSERVABILITY_OPENLIT_RECORDER_ENDPOINT`.

There is NO env var for `metric_export_interval_ms` — it is only settable in
code (default 60 000 ms).

## Citations

- path: `packages/ai-parrot/src/parrot/observability/config.py`
  lines: 347-470
  symbol: `ObservabilityConfig.from_env`
  excerpt: |
    endpoint = get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        values["otlp_endpoint"] = endpoint
    ...
    targets_raw = get("OTLP_TARGETS")
    if targets_raw:
        try:
            values["otlp_targets"] = [OtlpTarget(**t) for t in json.loads(targets_raw)]
        except Exception as exc:
            logger.warning("Malformed OTLP_TARGETS env var, ignoring: %s", exc)

- path: `packages/ai-parrot/src/parrot/observability/config.py`
  lines: 108-120
  symbol: `ObservabilityConfig.metric_export_interval_ms`

- path: `packages/ai-parrot/src/parrot/observability/config.py`
  lines: 472-482
  symbol: `_env_getter`

## Notes

`metric_export_interval_ms` defaulting to 60 s means a freshly-wired dashboard
shows nothing for up to a minute after the first LLM call — an important
expectation to set in any verification step.
