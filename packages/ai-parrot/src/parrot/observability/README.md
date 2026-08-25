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
    otlp_endpoint="http://localhost:4318",  # point this at your OpenLIT/OTLP collector
    enable_cost_tracking=True,
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

**FEAT-462 — Unified Telemetry Bus**: OpenLIT is no longer a Python SDK
dependency. It's a plain OTLP HTTP collector + dashboard that AI-Parrot
exports GenAI SemConv spans to directly — no `openlit.init()`, no
`observability-openlit` SDK extra, no version-conflicting `openai` pin.

This is the recommended path to get a **dashboard of LLM requests** (tokens,
USD cost, latency, model, errors) without writing any code:

```bash
# 1. Install the extra (aiohttp-only helper, see ai-parrot-openlit-bridge)
pip install 'ai-parrot[observability,observability-openlit]'

# 2. Launch a local OpenLIT collector — see
#    packages/ai-parrot-openlit-bridge/docker-compose.openlit.yml
docker compose -f packages/ai-parrot-openlit-bridge/docker-compose.openlit.yml up -d
parrot-openlit-check http://localhost:4318   # verify reachability

# 3. Point AI-Parrot at it (e.g. in your .env)
export OBSERVABILITY_ENABLED=true
export OBSERVABILITY_BACKEND=otel
export OBSERVABILITY_SERVICE_NAME=my-agent
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
```

Now build/use **any** bot — observability auto-boots on first construction and
exports OTLP traces + metrics. Open <http://localhost:3000> to see each LLM
request with tokens, cost and latency.

For **multiple** OTLP destinations at once (e.g. OpenLIT + Grafana Tempo),
set `OTLP_TARGETS` instead of the single `OTEL_EXPORTER_OTLP_ENDPOINT` — one
`BatchSpanProcessor` is attached per target on the shared `TracerProvider`:

```bash
export OTLP_TARGETS='[{"name":"openlit","endpoint":"http://localhost:4318"},{"name":"tempo","endpoint":"http://tempo:4318"}]'
```

For a **cost-only** OpenLIT dashboard without the full trace pipeline (e.g.
while running the lightweight `logging` backend), use the additive
`OpenLitUsageRecorder` instead:

```bash
export OBSERVABILITY_ENABLED=true
export OBSERVABILITY_OPENLIT_RECORDER=true
export OBSERVABILITY_OPENLIT_RECORDER_ENDPOINT=http://localhost:4318
```

Notes:

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

### Backends

| Backend | Install | When |
|---|---|---|
| `logging` (default) | none | Start here. Zero infra, zero network, minimal latency. |
| `prometheus` | `pip install 'ai-parrot[observability-prometheus]'` | Pull-based metrics + Grafana dashboards. Exposes `:9464/metrics`. |
| `otel` | `pip install 'ai-parrot[observability]'` | Full OTLP traces + metrics (delegates to `setup_telemetry`). Point `otlp_endpoint`/`otlp_targets` at OpenLIT, Tempo, SigNoz, etc. |

`usage_backend="traceloop"` and the `enable_openlit`/`enable_traceloop` config
flags are deprecated (FEAT-462): the former is remapped to `"otel"` with a
deprecation log, the latter two emit a `DeprecationWarning` and otherwise do
nothing — configure an OTLP target or the `OpenLitUsageRecorder` instead.

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
| `otlp_targets` | list[OtlpTarget] | `[]` | FEAT-462: multi-endpoint OTLP export. Empty → falls back to `otlp_endpoint` as a single implicit target. |
| `openlit_recorder_endpoint` | str \| None | `None` | FEAT-462: OTLP endpoint for the additive `OpenLitUsageRecorder` (usage-only spans, works independent of `usage_backend`). |
| `enable_openlit` | bool | `False` | **Deprecated (FEAT-462)** — no-op, emits a `DeprecationWarning`. Configure `otlp_targets`/`openlit_recorder_endpoint` instead. |
| `enable_traceloop` | bool | `False` | **Deprecated (FEAT-462)** — no-op, emits a `DeprecationWarning`. |
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
| `OTLP_TARGETS` | `config.otlp_targets` | FEAT-462: JSON list of `{"name","endpoint","headers"}`. Malformed JSON is logged and ignored (falls back to `otlp_endpoint`). |
| `OBSERVABILITY_OPENLIT_RECORDER` | `config.openlit_recorder_endpoint` | FEAT-462: boolean enable switch for the additive `OpenLitUsageRecorder`; defaults the endpoint to `otlp_endpoint`. |
| `OBSERVABILITY_OPENLIT_RECORDER_ENDPOINT` | `config.openlit_recorder_endpoint` | FEAT-462: explicit endpoint override for the recorder above. |
| `OBSERVABILITY_OPENLIT` | `config.enable_openlit` | **Deprecated (FEAT-462)** — no-op; emits a `DeprecationWarning`. |
| `OBSERVABILITY_TRACELOOP` | `config.enable_traceloop` | **Deprecated (FEAT-462)** — no-op; emits a `DeprecationWarning`. |
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
- **Enabled**: p50 overhead < 1 ms per `bot.ask()` round-trip on a
  typical developer machine.
- **Enabled + `OpenLitUsageRecorder`** (mocked exporter): p50 overhead < 5 ms.
- **`SimpleSpanProcessor` is forbidden** — `setup_telemetry` will raise `ConfigurationError`
  if one is detected. Always use `BatchSpanProcessor` (wired automatically).

These guarantees are enforced by `tests/integration/observability/test_perf.py`.

---

## OpenLIT contract

**FEAT-462**: OpenLIT is a deployment-time OTLP endpoint, not an SDK — there is
no `openlit.init()` call and no parent/child span-ordering concern anymore.
AI-Parrot's own `GenAIOpenTelemetrySubscriber` emits every GenAI SemConv span
directly; OpenLIT's dashboard reads them straight off the OTLP endpoint you
point `otlp_endpoint`/`otlp_targets` at. See `ai-parrot-openlit-bridge` for an
optional endpoint-reachability probe (`parrot-openlit-check`).

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
4. **Traces + `OpenLitUsageRecorder` (mocked exporter)** — the additive usage recorder
   receives a record on `AfterClientCallEvent` while the native trace subscriber
   independently still produces spans on the same event stream.
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

**"ConfigurationError: setup_telemetry already configured with a different ObservabilityConfig"**
`setup_telemetry` is idempotent for the same config but rejects a second call with
a different config. Call `shutdown_telemetry()` first to reconfigure.

**No data in OpenLIT UI**
1. Confirm the container is healthy: `docker compose ps`
2. Confirm `otlp_endpoint` matches the collector port (default: `http://localhost:4318`)
3. Verify the ClickHouse schema was initialised — check OpenLIT logs: `docker compose logs openlit-ui`
