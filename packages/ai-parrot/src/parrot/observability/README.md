# parrot.observability — OpenTelemetry + Cost Observability

OpenTelemetry-based observability for AI-Parrot: GenAI SemConv-compliant
traces, OTel metrics (counters + histograms), and USD cost tracking wired
against the FEAT-176 lifecycle event system.

---

## Quickstart

```python
from parrot.observability import ObservabilityConfig, setup_telemetry, shutdown_telemetry

# Boot the stack (idempotent)
setup_telemetry(ObservabilityConfig(
    enabled=True,
    service_name="my-agent",
    otlp_endpoint="http://localhost:4318",
    enable_cost_tracking=True,
    enable_openlit=True,   # requires: pip install 'ai-parrot[observability-openlit]'
))

# ... run your agent as usual ...

# Flush exporters on clean shutdown
shutdown_telemetry()
```

For a live demo stack (OpenLIT UI + ClickHouse + Prometheus):

```bash
cd packages/ai-parrot/src/parrot/observability/examples
docker compose -f docker-compose.observability.yml up -d
python basic_telemetry.py
```

See [examples/README.md](examples/README.md) for the full quickstart.

---

## Pluggable usage logging (no OpenTelemetry required)

For the common case — "just log model usage, tokens, and cost" — you do **not**
need the OTel SDK or a collector. A pluggable recorder layer fronted by a single
`AbstractLogger` interface lets you start with structured logs and swap to
Prometheus (or full OTel) by changing one environment variable.

### Auto-boot from environment variables

Set `OBSERVABILITY_ENABLED=true` and AI-Parrot activates usage recording
automatically on the first bot/client construction — no code changes:

```bash
export OBSERVABILITY_ENABLED=true       # backend defaults to "logging"
# optional:
export OBSERVABILITY_BACKEND=logging    # logging | prometheus | otel
export OBSERVABILITY_LOG_LEVEL=INFO
```

Each LLM call then emits one line on the `parrot.usage` logger:

```
llm-usage provider=openai model=gpt-4o input_tokens=1000 output_tokens=500 \
  total_tokens=1500 cost_usd=0.005000 cumulative_cost_usd=0.005000 \
  duration_ms=842.0 finish_reason=stop trace=<id>
```

The `logging` backend pulls in **no third-party dependency** and never imports
the OpenTelemetry SDK. Cost is computed via the bundled `CostCalculator`
(disable with `OBSERVABILITY_COST=false`).

### End-to-end with OpenLIT + OTLP (dashboards, zero code)

This is the recommended path to get a **dashboard of LLM requests** (tokens,
USD cost, latency, model, errors) without writing any code:

```bash
# 1. Install the extras
pip install 'ai-parrot[observability,observability-openlit]'

# 2. Launch the demo stack (OpenLIT UI :3000 + ClickHouse + Prometheus :9090)
docker compose -f packages/ai-parrot/src/parrot/observability/examples/docker-compose.observability.yml up -d

# 3. Point AI-Parrot at it (e.g. in your .env)
export OBSERVABILITY_ENABLED=true
export OBSERVABILITY_BACKEND=otel
export OBSERVABILITY_OPENLIT=true
export OBSERVABILITY_SERVICE_NAME=my-agent
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
```

Now build/use **any** bot — observability auto-boots on first construction and
exports OTLP traces + metrics. Open <http://localhost:3000> to see each LLM
request with tokens, cost and latency.

Notes:

- **OpenLIT escalates the backend.** Setting `OBSERVABILITY_OPENLIT=true` forces
  the `otel` path even if `OBSERVABILITY_BACKEND` is unset/`logging`, because
  OpenLIT needs the global `TracerProvider` that only `setup_telemetry` installs.
- **Graceful flush is automatic.** An `atexit` hook flushes the final
  `BatchSpanProcessor` / `PeriodicExportingMetricReader` batch on process exit;
  long-running servers also flush deterministically via the autonomous
  orchestrator's `stop()`. Call `shutdown_observability()` yourself if you manage
  your own lifecycle.
- **Sampling / PII.** Tune `OBSERVABILITY_SAMPLING` (0.0–1.0) for high-volume
  deployments; prompts/completions are **not** captured by default
  (`capture_prompts` / `capture_completions` are off — PII guard).
- **Custom pricing.** Point `PARROT_PRICING_PATH` at a dir of `<provider>.json`
  files to override the bundled cost tables.

### Simple local/dev with OpenLLMetry (Traceloop)

When you want a lightweight local/dev setup that shows the **actual prompts and
responses** in the trace (the one thing the native path withholds by default for
PII), use the `traceloop` backend. Keep OpenLIT for production:

```bash
pip install 'ai-parrot[observability,observability-traceloop]'

export OBSERVABILITY_ENABLED=true
export OBSERVABILITY_TRACELOOP=true          # forces backend=traceloop; OpenLIT stays off
export OBSERVABILITY_CAPTURE_CONTENT=true    # dev only — captures prompts/completions (PII)
export OBSERVABILITY_SERVICE_NAME=my-agent
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
```

How it works:

- **Traceloop owns one OTLP pipeline.** `Traceloop.init()` installs the global
  `TracerProvider`, exports to your collector, and auto-instruments the LLM SDKs
  (OpenAI/Anthropic/…) with content capture. AI-Parrot's native span/metric
  subscribers ride the *same* global provider, so you also get the agent/tool/
  client spans and usage/cost metrics — **one pipeline, no duplicate spans**.
- **Mutually exclusive with OpenLIT.** Setting `OBSERVABILITY_TRACELOOP=true`
  forces `backend=traceloop`; if `OBSERVABILITY_OPENLIT=true` is also set,
  Traceloop wins and OpenLIT is disabled with a warning. The `traceloop-sdk` is
  an independent optional extra — choosing OpenLIT never installs Traceloop and
  vice-versa.
- **Content capture is gated.** Prompts/completions are captured only when
  `OBSERVABILITY_CAPTURE_CONTENT=true` (maps to `capture_prompts` /
  `capture_completions`, which also sets Traceloop's `TRACELOOP_TRACE_CONTENT`).
  Leave it off outside dev/test.

Point it at any OTLP backend — the bundled OpenLIT stack at `:4318`, a local
Jaeger/Grafana Tempo, SigNoz, or the Traceloop cloud (set an API key).

### Backends

| Backend | Install | When |
|---|---|---|
| `logging` (default) | none | Start here. Zero infra, zero network, minimal latency. |
| `prometheus` | `pip install 'ai-parrot[observability-prometheus]'` | Pull-based metrics + Grafana dashboards. Exposes `:9464/metrics`. |
| `otel` | `pip install 'ai-parrot[observability]'` | Full OTLP traces + metrics (delegates to `setup_telemetry`). Add `observability-openlit` for the production OpenLIT backend. |
| `traceloop` | `pip install 'ai-parrot[observability,observability-traceloop]'` | **Local/dev**: OpenLLMetry (Traceloop) owns the OTLP pipeline + auto-instruments the LLM SDKs with prompt/completion capture. Mutually exclusive with OpenLIT. |

The Prometheus backend exposes `parrot_llm_requests_total`,
`parrot_llm_input_tokens_total`, `parrot_llm_output_tokens_total`,
`parrot_llm_cost_usd_total` (all labelled `{provider, model}`),
`parrot_llm_request_duration_seconds`, and `parrot_llm_tokens{type}`. A starter
dashboard ships at
[`examples/grafana-dashboards/parrot-usage.json`](examples/grafana-dashboards/parrot-usage.json).

### Programmatic use / custom backends

```python
from parrot.observability import (
    UsageRecord, AbstractLogger, UsageRecordingSubscriber, LoggingUsageRecorder,
)
from parrot.observability.cost import CostCalculator
from parrot.core.events.lifecycle import get_global_registry

class MyRecorder(AbstractLogger):
    name = "my-sink"
    async def record(self, record: UsageRecord) -> None:
        ...  # ship `record` (provider, model, tokens, cost_usd, …) anywhere

sub = UsageRecordingSubscriber(
    recorders=[LoggingUsageRecorder(), MyRecorder()],
    cost_calculator=CostCalculator(),
)
get_global_registry().add_provider(sub)
```

### How events reach the recorder

LLM clients emit their call lifecycle events on an **isolated** registry
(`forward_to_global=False`) so high-frequency stream chunks stay local. The
three call events (`Before`/`After`/`Failed`) are explicitly bridged to the
**global** registry via `EventRegistry.forward_to_global`, which is a guarded
no-op when no global subscriber is listening. This is what lets a single
globally-registered subscriber (the usage recorder *or* the OTel
`MetricsSubscriber`) observe every agent's LLM calls.

---

## Configuration

`ObservabilityConfig` is a Pydantic v2 model. All fields have safe defaults.

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `False` | Master switch. `False` → `setup_telemetry` is a no-op. |
| `service_name` | str | `"ai-parrot"` | OTel `service.name` resource attribute. |
| `service_version` | str \| None | `None` | OTel `service.version`. Defaults to installed package version. |
| `service_instance_id` | str \| None | `None` | OTel `service.instance.id`. Defaults to `"{hostname}-{pid}"`. |
| `otlp_endpoint` | str | `"http://localhost:4318"` | OTLP collector base URL. |
| `otlp_protocol` | `"http/protobuf"` \| `"grpc"` | `"http/protobuf"` | Transport protocol. gRPC requires `grpcio`. |
| `otlp_headers` | dict[str, str] | `{}` | Extra HTTP headers (e.g. auth tokens). |
| `enable_traces` | bool | `True` | Subscribe `GenAIOpenTelemetrySubscriber`. |
| `enable_metrics` | bool | `True` | Subscribe `MetricsSubscriber`. |
| `enable_cost_tracking` | bool | `True` | Build a `CostCalculator` and inject into subscribers. |
| `enable_openlit` | bool | `False` | Call `openlit.init()` for auto-instrumentation. |
| `sampling_ratio` | float | `1.0` | `TraceIdRatioBased` sampler rate `[0.0, 1.0]`. |
| `capture_prompts` | bool | `False` | Include system-prompt SHA-256 hashes in spans. **PII guard: default off.** |
| `capture_completions` | bool | `False` | Add per-chunk span events for streaming. **PII guard: default off.** |
| `metric_export_interval_ms` | int | `60_000` | `PeriodicExportingMetricReader` interval (ms). |
| `histogram_buckets` | list[float] \| None | `None` | Histogram bucket boundaries. `None` → `[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0, 60.0]` (LLM-tuned). |
| `pricing_override_path` | str \| None | `None` | Directory of `<provider>.json` pricing override files. |

---

## navconfig / env-var keys

`setup_telemetry` reads these environment variables via `navconfig.config.get(key, fallback=None)`:

| Env var | Maps to | Notes |
|---|---|---|
| `OBSERVABILITY_ENABLED` | `config.enabled` | Set to `"true"` or `"1"` to enable. |
| `OBSERVABILITY_SERVICE_NAME` | `config.service_name` | Overrides the default `"ai-parrot"`. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `config.otlp_endpoint` | Standard OTel env var; navconfig reads it. |
| `OBSERVABILITY_OPENLIT` | `config.enable_openlit` | Set to `"true"` to enable OpenLIT auto-instrumentation. |
| `OBSERVABILITY_COST` | `config.enable_cost_tracking` | Set to `"false"` to disable cost tracking. |
| `OBSERVABILITY_SAMPLING` | `config.sampling_ratio` | Float string `"0.1"` → 10% sampling. |
| `PARROT_PRICING_PATH` | `config.pricing_override_path` | Path to a custom pricing directory. |

Note: `setup_telemetry` itself only auto-reads `PARROT_PRICING_PATH`. To build a
config from **all** the variables above, use `ObservabilityConfig.from_env()`, or
rely on the auto-boot (`OBSERVABILITY_ENABLED=true`) which calls it for you. The
auto-boot additionally reads `OBSERVABILITY_BACKEND`, `OBSERVABILITY_LOG_LEVEL`,
`OBSERVABILITY_PROM_PORT`, and `OBSERVABILITY_PROM_ADDR` (see the pluggable
usage-logging section above).

---

## PII contract

By default, AI-Parrot captures **zero user content** in spans or metrics:

- `capture_prompts=False` (default) — no system prompt text is stored; only a SHA-256 hash when enabled.
- `capture_completions=False` (default) — streaming response chunks are never stored.
- `otlp_headers` are not logged.

Enabling `capture_prompts=True` or `capture_completions=True` is the **user's responsibility**.
AI-Parrot ships no default redactor. If you enable these, ensure your OTLP pipeline
is GDPR/CCPA compliant before production use.

---

## Performance contract

- **Disabled** (`config.enabled=False`): ~0 ns overhead; `setup_telemetry` returns
  immediately without importing the OTel SDK.
- **Enabled, no OpenLIT**: p50 overhead < 1 ms per `bot.ask()` round-trip on a
  typical developer machine.
- **Enabled + OpenLIT** (mocked): p50 overhead < 5 ms.
- **`SimpleSpanProcessor` is forbidden** — `setup_telemetry` will raise `ConfigurationError`
  if one is detected. Always use `BatchSpanProcessor` (wired automatically).

These guarantees are enforced by `tests/integration/observability/test_perf.py`.

---

## OpenLIT contract

OpenLIT auto-spans are **children** of AI-Parrot's own spans, not siblings.

This is guaranteed automatically: `setup_telemetry` installs the global `TracerProvider`
**before** calling `openlit.init()`. OpenLIT inherits the active provider and the active
span context, so its spans nest correctly under ours.

**Do not reorder** `setup_telemetry` and `openlit.init()` calls. If you call
`openlit.init()` manually before `setup_telemetry`, parent-child relationships
may be reversed.

---

## Examples

- Live demo stack: [`examples/docker-compose.observability.yml`](examples/docker-compose.observability.yml)
- Demo script: [`examples/basic_telemetry.py`](examples/basic_telemetry.py)
- Grafana dashboard: [`examples/grafana-dashboards/parrot-overview.json`](examples/grafana-dashboards/parrot-overview.json)
- Full quickstart: [`examples/README.md`](examples/README.md)

---

## PoC scenarios

The integration test suite at
`tests/integration/observability/test_poc.py`
covers 5 scenarios:

1. **Traces only** (`enable_metrics=False`) — span exporter captures spans.
2. **Metrics only** (`enable_traces=False`) — metric reader collects counters/histograms.
3. **Traces + metrics + cost** — both exporter and reader are populated; cost counter updated.
4. **Traces + OpenLIT (mocked)** — `openlit.init` called exactly once; subscriber still works.
5. **Sampling = 10%** — 100 requests yield ~10 spans (±50% CI tolerance).

Run with:

```bash
pytest packages/ai-parrot/tests/integration/observability/test_poc.py -v
pytest packages/ai-parrot/tests/integration/observability/test_perf.py -v
```

---

## Cost pricing

Bundled pricing tables live in `parrot/observability/pricing/*.json` (one file per provider).
The format is:

```json
{
  "<model-name>": {
    "input": <price-per-1M-tokens>,
    "output": <price-per-1M-tokens>,
    "cached_input": <price-per-1M-tokens-optional>
  }
}
```

To override prices (e.g. for enterprise agreements):

```bash
export PARROT_PRICING_PATH=/path/to/my/pricing
```

Or set `config.pricing_override_path` directly. Override files are deep-merged
over the bundled tables on a per-model basis.

A staleness warning is logged if any pricing file is older than 90 days
(configurable via `CostCalculator(stale_warn_days=...)` directly).

---

## Troubleshooting

**"ModuleNotFoundError: opentelemetry.exporter.otlp..."**
Install the `observability` extra:
```bash
pip install 'ai-parrot[observability]'
```

**"ImportError: enable_openlit=True requires the 'observability-openlit' extra"**
Install:
```bash
pip install 'ai-parrot[observability-openlit]'
```

**OpenLIT spans appear as siblings instead of children of AI-Parrot spans**
`openlit.init()` was called before `setup_telemetry()`. Always call
`setup_telemetry()` first. Setting `enable_openlit=True` in `ObservabilityConfig`
guarantees the correct order.

**"ConfigurationError: setup_telemetry already configured with a different ObservabilityConfig"**
`setup_telemetry` is idempotent for the same config but rejects a second call with
a different config. Call `shutdown_telemetry()` first to reconfigure.

**No data in OpenLIT UI**
1. Confirm the container is healthy: `docker compose ps`
2. Confirm `otlp_endpoint` matches the collector port (default: `http://localhost:4318`)
3. Verify the ClickHouse schema was initialised — check OpenLIT logs: `docker compose logs openlit-ui`
