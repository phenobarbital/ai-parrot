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
             └─ backend=otel        → setup_telemetry(): OTLP traces + metrics,
                                       one BatchSpanProcessor per otlp_targets entry
```

**FEAT-462 — Unified Telemetry Bus.** OpenLIT and OpenLLMetry (Traceloop) used
to be monkey-patching SDKs that auto-instrumented the provider SDKs and were
mutually exclusive. Both SDK dependencies are gone: `openlit`/`traceloop-sdk`
pinned conflicting `openai` version ranges, which is exactly the conflict this
feature eliminates. OpenLIT (and any other OTLP-compatible backend — Tempo,
SigNoz, …) is now a **pure deployment-time OTLP endpoint** you point
`otlp_endpoint`/`otlp_targets` at — no SDK, no install-time conflict.
`usage_backend="traceloop"` is remapped to `"otel"` with a deprecation log; the
`enable_openlit`/`enable_traceloop` config flags remain for backward compat but
are now no-ops that only emit a `DeprecationWarning`.

For a **cost-only** OpenLIT dashboard without the full trace pipeline, use the
additive `OpenLitUsageRecorder` (`OBSERVABILITY_OPENLIT_RECORDER=true`) — it
pushes `UsageRecord`s as GenAI SemConv spans via its own private
`TracerProvider`, independent of `usage_backend`.

Lifecycle events (FEAT-176) — `BeforeClientCallEvent` / `AfterClientCallEvent` /
`ClientCallFailedEvent`, tool events, invoke events — are the instrumentation
seam. Subscribers (`GenAIOpenTelemetrySubscriber`, `MetricsSubscriber`,
`UsageRecordingSubscriber`) convert them into GenAI SemConv spans, OTel metrics,
and cost records. Sensitive data is hashed; prompts/completions are **not**
captured by default (PII guard).

## 10.2 Get a dashboard of LLM requests (Prometheus + Grafana)

```bash
# 1. Install the extra (aiohttp-only helper — no monkey-patching SDK)
pip install 'ai-parrot[observability]'

# 2. The local stack (already running for most dev setups):
docker compose -f docker/prometheus/docker-compose.yml up -d
docker compose -f docker/grafana/docker-compose.yml up -d --build

# 3. Point AI-Parrot at the Prometheus OTLP write receiver (.env)
OBSERVABILITY_ENABLED=true
OBSERVABILITY_BACKEND=otel
OBSERVABILITY_SERVICE_NAME=my-agent
# Metrics -> the local Prometheus OTLP write receiver. BASE URL ONLY: the
# exporter appends /v1/metrics itself (exporters.py:152).
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:9090/api/v1/otlp
# Prometheus 2.x serves no /v1/traces, so switch the trace subscriber off.
OBSERVABILITY_TRACES=false
# Optional: OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS=10000 to see metrics sooner than 60 s.
```

A ready-to-copy, secret-free block lives at `env/.env.observability.example`.
Build/use any bot → open the **AI-Parrot — LLM Usage & Cost** dashboard,
provisioned automatically into Grafana's **AI-Parrot** folder from
`docker/grafana/provisioning/dashboards-parrot/` (deep link and empty-dashboard
diagnostics: `docker/grafana/README.md`) — see each LLM request with tokens, USD
cost, latency, model, provider and, since FEAT-228, **agent**.

For **traces**, OpenLIT remains a supported destination (the
`ai-parrot-openlit-bridge` distribution and its collector are unchanged): set
`OBSERVABILITY_TRACES=true` and either point `OTEL_EXPORTER_OTLP_ENDPOINT` at
OpenLIT's receiver, or list OpenLIT in `OTLP_TARGETS` (a JSON list of
`{"name","endpoint","headers"}`). Either choice sends metrics there too; one
`BatchSpanProcessor` and one `PeriodicExportingMetricReader` are attached per
target. `parrot-openlit-check http://localhost:4318` verifies OpenLIT's own
receiver is reachable before pointing signals at it.

### Migrating split routing (FEAT-705)

| Previous routing | FEAT-705 result |
|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` points to Prometheus and `OTLP_TARGETS` lists OpenLIT | OpenLIT receives both traces and metrics; Prometheus receives neither. |

To keep metrics in Prometheus and traces in OpenLIT, run an OTLP collector with
separate signal pipelines. Point `OTEL_EXPORTER_OTLP_ENDPOINT` at that collector,
leave `OTLP_TARGETS` unset, and set both signal switches to `true` with nonzero
sampling. Listing Prometheus and OpenLIT together is not equivalent: Prometheus
rejects `/v1/traces`.

`OBSERVABILITY_BACKEND=prometheus` is a *different*, non-OTel path: it exposes
`parrot_llm_*` counters via `prometheus_client` on `:9464` for Prometheus to
scrape, carries only `(provider, model)` labels, and cannot answer "cost by
agent". Use it only if you specifically want that.

## 10.3 Configuration reference

| Env var | Field | Default |
|---|---|---|
| `OBSERVABILITY_ENABLED` | master switch | `false` |
| `OBSERVABILITY_BACKEND` | `none`·`logging`·`prometheus`·`otel` | `none` → `logging` when enabled |
| `OTLP_TARGETS` | multi-endpoint OTLP export of traces **and** metrics (JSON list); replaces `OTEL_EXPORTER_OTLP_ENDPOINT` when nonempty | `[]` |
| `OBSERVABILITY_OPENLIT_RECORDER` / `_ENDPOINT` | additive `OpenLitUsageRecorder` (usage-only spans) | `false` / unset |
| `OBSERVABILITY_OPENLIT` / `OBSERVABILITY_TRACELOOP` | **deprecated** — no-op, `DeprecationWarning` | `false` |
| `OBSERVABILITY_CAPTURE_CONTENT` | capture prompts/completions (PII; dev only) | `false` |
| `OBSERVABILITY_SERVICE_NAME` | `service.name` | `ai-parrot` |
| `OBSERVABILITY_COST` | USD cost tracking | `true` |
| `OBSERVABILITY_SAMPLING` | trace sampling ratio (0.0–1.0) | `1.0` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP **base** URL; the single implicit target for both signals when `OTLP_TARGETS` is empty; ignored when it is set | `http://localhost:4318` |
| `OBSERVABILITY_TRACES` | trace subscriber switch | `true` |
| `OBSERVABILITY_METRICS` | metrics subscriber switch | `true` |
| `OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS` | metric export interval in milliseconds | `60000` |
| `OBSERVABILITY_PROM_PORT` / `_ADDR` | Prometheus exposition | `9464` / `0.0.0.0` |
| `PARROT_PRICING_PATH` | custom pricing dir | bundled tables |

> Expect up to `OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS` (60 s by default) before the first metrics appear.
>
> A ready-to-copy block lives at `env/.env.observability.example`.

## 10.4 Lifecycle & graceful flush

The batch span/metric exporters must flush on shutdown or the last requests are
lost. AI-Parrot handles this automatically:

- An **`atexit`** hook (registered on first boot) flushes on process exit for any
  entrypoint — CLI, scripts, gunicorn workers.
- The autonomous server flushes **deterministically** in
  `AutonomousOrchestrator.stop()` before the worker exits.
- If you own the lifecycle, call `shutdown_observability()` yourself (aggregates
  the OTel and lightweight teardown paths; idempotent and safe when disabled).

> **Short-lived callers (scripts/CLIs/one-shot lambdas).**
> `_emit_after_call` and `_emit_failed_call` now **await** the global
> forwarding directly (since the post-FEAT-548 fix), so the end-of-call
> events — which carry all the metrics data — land before the caller's next
> line executes. The earlier fire-and-forget race (FEAT-548 Finding #2) is
> fixed for these events.
>
> `_emit_before_call` remains fire-and-forget (it is synchronous and
> carries no metrics data — the `gen_ai.client.request.count` counter is
> purely informational). If you need the request counter to land reliably
> in a short-lived script, call `await drain_lifecycle_events()` (from
> `parrot.observability.setup`) before `shutdown_telemetry()`:
>
> ```python
> from parrot.observability.setup import drain_lifecycle_events, shutdown_telemetry
>
> result = await client.ask("hello", model="gpt-4o")
> await drain_lifecycle_events()   # drains fire-and-forget Before events
> shutdown_telemetry()
> ```
>
> Long-running processes (servers, the autonomous orchestrator) are
> unaffected — they naturally yield between calls.
