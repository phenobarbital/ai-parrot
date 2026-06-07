# 10. Observability — OpenLIT + OpenTelemetry

> Part of the [Exposure, Interoperability & Hardening](README.md) set.
> Previous: [Ontologic RAG](09-ontologic-rag.md)

AI-Parrot ships a first-class observability subsystem that turns every LLM
request into OpenTelemetry traces + metrics and an itemised USD cost, with an
optional [OpenLIT](https://openlit.io) backend for ready-made dashboards. It is
**opt-in, env-driven, and zero-code**: nothing imports the OpenTelemetry SDK
until you enable it, and once enabled it auto-boots the first time any
bot/client/tool is constructed.

Implementation: `parrot.observability` (package `ai-parrot`). Full reference:
[`packages/ai-parrot/src/parrot/observability/README.md`](../../packages/ai-parrot/src/parrot/observability/README.md).

## 10.1 How it wires in

```
bot/client/tool construction
   └─ EventEmitterMixin._init_events
        └─ ensure_observability_bootstrapped()   ← reads OBSERVABILITY_* env
             ├─ backend=logging     → one structured line per LLM call (no infra)
             ├─ backend=prometheus  → counters/histograms on :9464/metrics
             └─ backend=otel        → setup_telemetry(): OTLP traces + metrics
                                       (+ openlit.init when OBSERVABILITY_OPENLIT=true)
```

Lifecycle events (FEAT-176) — `BeforeClientCallEvent` / `AfterClientCallEvent` /
`ClientCallFailedEvent`, tool events, invoke events — are the instrumentation
seam. Subscribers (`GenAIOpenTelemetrySubscriber`, `MetricsSubscriber`,
`UsageRecordingSubscriber`) convert them into GenAI SemConv spans, OTel metrics,
and cost records. Sensitive data is hashed; prompts/completions are **not**
captured by default (PII guard).

## 10.2 Get a dashboard of LLM requests (OpenLIT + OTLP)

```bash
# 1. Install extras
pip install 'ai-parrot[observability,observability-openlit]'

# 2. Launch the demo stack: OpenLIT UI :3000 + ClickHouse + Prometheus :9090
docker compose -f packages/ai-parrot/src/parrot/observability/examples/docker-compose.observability.yml up -d

# 3. Point AI-Parrot at the collector (.env)
OBSERVABILITY_ENABLED=true
OBSERVABILITY_BACKEND=otel
OBSERVABILITY_OPENLIT=true
OBSERVABILITY_SERVICE_NAME=my-agent
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
```

Build/use any bot → open <http://localhost:3000> to see each LLM request with
tokens, USD cost, latency, model and errors. For Prometheus + Grafana, set
`OBSERVABILITY_BACKEND=prometheus` and import the dashboards under
`packages/ai-parrot/src/parrot/observability/examples/grafana-dashboards/`.

## 10.3 Configuration reference

| Env var | Field | Default |
|---|---|---|
| `OBSERVABILITY_ENABLED` | master switch | `false` |
| `OBSERVABILITY_BACKEND` | `none`·`logging`·`prometheus`·`otel` | `none` → `logging` when enabled |
| `OBSERVABILITY_OPENLIT` | init OpenLIT (escalates backend to `otel`) | `false` |
| `OBSERVABILITY_SERVICE_NAME` | `service.name` | `ai-parrot` |
| `OBSERVABILITY_COST` | USD cost tracking | `true` |
| `OBSERVABILITY_SAMPLING` | trace sampling ratio (0.0–1.0) | `1.0` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP collector base URL | `http://localhost:4318` |
| `OBSERVABILITY_PROM_PORT` / `_ADDR` | Prometheus exposition | `9464` / `0.0.0.0` |
| `PARROT_PRICING_PATH` | custom pricing dir | bundled tables |

## 10.4 Lifecycle & graceful flush

The batch span/metric exporters must flush on shutdown or the last requests are
lost. AI-Parrot handles this automatically:

- An **`atexit`** hook (registered on first boot) flushes on process exit for any
  entrypoint — CLI, scripts, gunicorn workers.
- The autonomous server flushes **deterministically** in
  `AutonomousOrchestrator.stop()` before the worker exits.
- If you own the lifecycle, call `shutdown_observability()` yourself (aggregates
  the OTel and lightweight teardown paths; idempotent and safe when disabled).
