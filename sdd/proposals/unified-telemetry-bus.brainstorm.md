---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Unified Telemetry Bus

**Date**: 2026-08-25
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option B

---

## Problem Statement

OpenLIT 1.45 hard-caps `openai>=1.92.0,<3.0.0` while ai-parrot pins
`openai==3.3.1`. This creates an irreconcilable dependency conflict requiring
**11 `conflicting-groups` entries** in the workspace `pyproject.toml` — a
maintenance burden that grows every time a new extra touches `openai`.

The root cause: both OpenLIT and Traceloop work by **monkey-patching LLM SDK
internals**, coupling their version constraints to ours. This is architecturally
unnecessary because ai-parrot already wraps every LLM call through
`AbstractClient`, which emits rich lifecycle events (`AfterClientCallEvent`,
`BeforeClientCallEvent`, etc.) with all the telemetry data these backends need.

**Who is affected:**
- **Operators** cannot install `ai-parrot[observability-openlit,openai]` together.
- **Developers** must maintain a growing `conflicting-groups` table.
- **CI/CD** uses a split install strategy to work around the conflict.

**Why now:** OpenAI SDK 3.x has been out since May 2026 (~3 months). OpenLIT
shows no sign of lifting the cap. The conflict is permanent unless we decouple.

## Constraints & Requirements

- Must not break existing `OBSERVABILITY_ENABLED=true` + `OBSERVABILITY_BACKEND=otel` deployments
- Must preserve OpenLIT dashboard compatibility (same OTLP span attribute names)
- Must keep the PII guards (no prompt/completion content in spans by default)
- The `AbstractLogger` / `UsageRecordingSubscriber` fan-out pattern must remain for non-OTel backends (logging, prometheus)
- `navigator-eventbus` is already a dependency (0.2.3) — no new packages needed for the bus layer
- Multi-endpoint OTLP targets share global protocol/sampling/batch settings; each target specifies only endpoint URL + optional auth headers
- The repurposed extras (`observability-openlit`, `observability-traceloop`) install a minimal bridge helper, not the SDK itself

---

## Options Explored

### Option A: Pure OTLP — Drop Monkey-Patching SDKs

Replace OpenLIT and Traceloop Python SDK dependencies with pure OTLP export
from our native lifecycle event system. The `GenAIOpenTelemetrySubscriber`
already emits GenAI SemConv-compliant spans; we add the 2 missing attributes
(`gen_ai.operation.name`, `gen_ai.usage.cost`) and configure multiple OTLP
exporters — one per target platform.

`setup_telemetry()` gains an `otlp_targets` config: a list of
`OtlpTarget(name, endpoint, headers)` objects. Each target gets its own
`BatchSpanProcessor` + `OTLPSpanExporter` attached to the shared
`TracerProvider`. OpenLIT and Traceloop become deployment-time endpoint URLs,
not install-time packages.

The `openlit` and `traceloop-sdk` packages are removed. The extras are
repurposed: `observability-openlit` installs a lightweight
`ai-parrot-openlit-bridge` that validates the OpenLIT endpoint and provides a
health-check CLI. Same for Traceloop.

✅ **Pros:**
- Eliminates the dependency conflict entirely — removes all 11 `conflicting-groups`
- Minimal code change (~100 lines: config model, exporter factory, attribute additions)
- No new architectural concepts — extends existing patterns
- OpenLIT dashboard already reads standard GenAI SemConv OTLP spans
- Simpler boot path: no more `openlit.init()` / `Traceloop.init()` + disabled instrumentor lists

❌ **Cons:**
- Loses OpenLIT's auto-instrumentation of non-LLM libraries (DB, HTTP, etc.) — but these are already disabled in our config
- No recorder-level integration — usage data only flows through OTel spans, not through the `AbstractLogger` fan-out
- Testing requires a running OTLP collector to verify end-to-end

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `opentelemetry-sdk` | TracerProvider, BatchSpanProcessor | Already a dependency (>=1.25,<2.0) |
| `opentelemetry-exporter-otlp-proto-http` | OTLP HTTP exporter | Already a dependency |
| `opentelemetry-semantic-conventions` | GenAI SemConv attribute constants | Already a dependency |

🔗 **Existing Code to Reuse:**
- `parrot/observability/exporters.py` — `make_span_exporter()` / `make_metric_exporter()` factories (extend for multi-target)
- `parrot/observability/config.py` — `ObservabilityConfig` model (add `otlp_targets` field)
- `parrot/observability/attributes.py` — attribute builders (add `gen_ai.operation.name` and rename cost attr)
- `parrot/observability/setup.py` — `setup_telemetry()` (loop over targets, one BSP per target)

---

### Option B: Pure OTLP + OpenLIT Usage Recorder

Everything from Option A, plus a new `AbstractLogger` backend
(`OpenLitUsageRecorder`) that converts `UsageRecord` objects into OTel spans
and pushes them via a dedicated OTLP exporter to the OpenLIT endpoint. This
gives the OpenLIT dashboard richer per-call usage data (cost breakdowns,
per-agent views) through the same fan-out path that the logging and Prometheus
recorders use.

The recorder wraps an `OTLPSpanExporter` internally, creating one span per
`UsageRecord` with the full set of GenAI SemConv attributes plus cost
attributes. It operates independently of the main trace pipeline — even when
`usage_backend="logging"` (no OTel SDK for traces), the recorder still pushes
usage spans to OpenLIT.

✅ **Pros:**
- All benefits of Option A (dependency conflict resolved, multi-endpoint)
- OpenLIT dashboard gets usage data even when the full OTel trace pipeline is disabled
- Follows the established `AbstractLogger` pattern — consistent with `LoggingUsageRecorder` and `PrometheusUsageRecorder`
- Usage data and trace data can go to different endpoints (e.g., traces → your collector, usage → OpenLIT)
- The recorder is opt-in via config — zero overhead when not configured

❌ **Cons:**
- More code than Option A (~200 lines: recorder + factory integration + tests)
- Slight redundancy: when the full OTel pipeline is active AND the recorder is active, usage data reaches OpenLIT through two paths (trace spans + usage spans). Mitigated by documenting the config guidance.
- The recorder creates standalone spans (not nested under the trace hierarchy) — OpenLIT must correlate by `trace_id`

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `opentelemetry-sdk` | TracerProvider, BatchSpanProcessor | Already a dependency |
| `opentelemetry-exporter-otlp-proto-http` | OTLP HTTP exporter | Already a dependency |
| `opentelemetry-semantic-conventions` | GenAI SemConv attributes | Already a dependency |

🔗 **Existing Code to Reuse:**
- Everything from Option A, plus:
- `parrot/observability/recorders/base.py` — `AbstractLogger` base class (line 16)
- `parrot/observability/recorders/models.py` — `UsageRecord` model (line 31)
- `parrot/observability/recorders/factory.py` — `build_recorders_from_config()` (add OpenLIT recorder branch)
- `parrot/observability/recorders/prometheus_recorder.py` — pattern reference for a non-trivial recorder
- `parrot/observability/recorders/subscriber.py` — `UsageRecordingSubscriber` fan-out (no changes needed)

---

### Option C: EventBus-First Telemetry Architecture

Forward all lifecycle events to the `navigator-eventbus` `EventBus` (Redis-backed)
via the existing `forward_to_bus=True` bridge. Write telemetry consumers as
`EventBus` subscribers that export to OpenLIT, Traceloop, or any custom backend.
The EventBus becomes the universal telemetry distribution plane.

Each consumer registers a pattern subscription on the bus (e.g.,
`telemetry.client.*`) and receives events cross-process. The
`CompositeBackend` fans out to multiple transport backends (Redis pub/sub +
Redis streams for persistence). `DLQHandler` catches export failures for
retry.

The `GenAIOpenTelemetrySubscriber` and `MetricsSubscriber` migrate from direct
`EventRegistry` subscriptions to `EventBus` consumers, gaining cross-process
delivery and DLQ for free.

✅ **Pros:**
- Cross-process telemetry: multiple services (ai-parrot-server, workers, agents) share one telemetry bus
- Dead-letter queue for export failures — no lost telemetry
- Dynamic consumer registration at runtime — add/remove backends without restart
- Backpressure handling built into `navigator-eventbus`
- Fully decoupled: producers (AbstractClient) know nothing about consumers

❌ **Cons:**
- Redis round-trip on every LLM call's telemetry event path — added latency (~1-5ms per event)
- Significant architectural change — all existing subscribers must be refactored to bus consumers
- Over-engineered for the current deployment (single-process, no cross-service telemetry need today)
- Redis becomes a hard dependency for observability (currently optional)
- Testing complexity: requires Redis for integration tests
- Does NOT solve the immediate dependency conflict without also doing Option A's work

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-eventbus` | Async event bus + backends | Already a dependency (0.2.3) |
| `asyncdb` | Redis connection (for bus backends) | Already a dependency |
| `opentelemetry-sdk` | OTel span/metric generation in consumers | Already a dependency |

🔗 **Existing Code to Reuse:**
- `navigator_eventbus.EventBus` — `publish()`, `subscribe()`, `emit()`
- `navigator_eventbus.backends.CompositeBackend` — multi-backend fan-out
- `navigator_eventbus.backends.RedisStreamsBackend` — persistent event delivery
- `navigator_eventbus.dlq.DLQHandler` — dead-letter queue for failures
- `navigator_eventbus.lifecycle.EventRegistry.subscribe(..., forward_to_bus=True)` — existing bridge
- All existing observability subscribers (refactored to bus consumers)

---

### Option D: Hybrid — Option B Now, EventBus Later

Implement Option B (pure OTLP + OpenLIT recorder) as the immediate solution.
Design the architecture so the EventBus layer (Option C) can be added
non-disruptively as a follow-up feature when cross-process telemetry becomes a
real requirement.

Specifically:
1. **Now (this FEAT):** Option B — drop SDKs, multi-endpoint OTLP, OpenLIT
   recorder. Resolves the conflict.
2. **Later (separate FEAT):** Add `forward_to_bus=True` on the telemetry
   subscriptions. Write bus-side consumers that wrap the same
   `GenAIOpenTelemetrySubscriber` / `MetricsSubscriber` / `OpenLitUsageRecorder`.
   The in-process path remains the default; bus path is opt-in via
   `OBSERVABILITY_BUS=true`.

✅ **Pros:**
- Solves the immediate pain (dependency conflict) with medium effort
- Leaves the door open for cross-process telemetry without over-building now
- Clear migration path: in-process → bus is additive, not breaking
- Each phase is independently valuable and testable

❌ **Cons:**
- Two features instead of one (but each is self-contained)
- The "design for bus" constraint adds minor complexity to Option B's implementation (interface boundaries)

📊 **Effort:** Medium (Phase 1) + Medium (Phase 2, future)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| Phase 1: same as Option B | | |
| Phase 2: same as Option C | | |

🔗 **Existing Code to Reuse:**
- Phase 1: same as Option B
- Phase 2: same as Option C

---

## Recommendation

**Option B** is recommended because:

1. **It solves the root problem** — the `openlit`/`openai` dependency conflict
   is eliminated by dropping the monkey-patching SDKs entirely.
2. **The OpenLIT recorder fills a real gap** — operators want per-call cost and
   usage data in OpenLIT dashboards even when the full OTel trace pipeline is
   not active (e.g., lightweight `usage_backend="logging"` deploys that still
   want OpenLIT cost visibility).
3. **It follows established patterns** — the `AbstractLogger` recorder model is
   well-tested (`LoggingUsageRecorder`, `PrometheusUsageRecorder`) and the new
   recorder fits the same interface.
4. **The multi-endpoint OTLP support is genuinely useful** — operators running
   both OpenLIT and their own collector (Grafana Tempo, Jaeger) need two
   exporters without running a separate OTel Collector sidecar.
5. **Medium effort is justified** — the extra ~100 lines over Option A buy real
   functionality (recorder), not just architectural purity.

**What we're trading off:** Option B does not include cross-process telemetry
(Option C). This is acceptable because there is no current multi-service
deployment that needs it. When that need arises, the `forward_to_bus=True`
bridge in `navigator-eventbus` makes the upgrade non-breaking (Option D path).

---

## Feature Description

### User-Facing Behavior

**For operators:**
- `OBSERVABILITY_ENABLED=true` + `OBSERVABILITY_BACKEND=otel` continues to work
  identically. Spans flow to the configured OTLP endpoint with the same
  attributes.
- New env var `OTLP_TARGETS` accepts a JSON list of targets:
  ```
  OTLP_TARGETS='[{"name":"openlit","endpoint":"http://openlit:4318"},{"name":"tempo","endpoint":"http://tempo:4318","headers":{"Authorization":"Bearer xxx"}}]'
  ```
  When set, each target gets its own `BatchSpanProcessor` + exporter. The
  legacy `OTEL_EXPORTER_OTLP_ENDPOINT` still works as the single-target
  default.
- New env var `OBSERVABILITY_OPENLIT_RECORDER=true` enables the OpenLIT usage
  recorder (pushes `UsageRecord` data as OTel spans to the OpenLIT endpoint).
- `pip install ai-parrot[observability-openlit]` no longer installs the
  `openlit` SDK. It installs `ai-parrot-openlit-bridge` — a lightweight
  package that validates the OpenLIT endpoint is reachable and provides
  `parrot-openlit-check` CLI command.
- `OBSERVABILITY_OPENLIT=true` and `OBSERVABILITY_TRACELOOP=true` env vars are
  deprecated with a runtime warning pointing to the new OTLP-only config path.

**For developers:**
- The 11 `conflicting-groups` entries for openlit are removed from
  `pyproject.toml`.
- `pip install ai-parrot[openai,observability-openlit]` works without conflict.
- `openlit_integration.py` and `traceloop_integration.py` are removed.

### Internal Behavior

```
AbstractClient.ask()
    │
    emit BeforeClientCallEvent / AfterClientCallEvent
    │
    ▼
EventRegistry (in-process lifecycle bus)
    │
    ├── GenAIOpenTelemetrySubscriber
    │       → TracerProvider (GenAI SemConv spans)
    │             ├── BatchSpanProcessor → OTLP target 1 (OpenLIT)
    │             ├── BatchSpanProcessor → OTLP target 2 (Tempo)
    │             └── BatchSpanProcessor → OTLP target N
    │
    ├── MetricsSubscriber
    │       → MeterProvider
    │             └── PeriodicExportingMetricReader → OTLP metric exporter
    │
    └── UsageRecordingSubscriber
            → fan-out to AbstractLogger backends:
                ├── LoggingUsageRecorder (structured logs)
                ├── PrometheusUsageRecorder (pull-based metrics)
                └── OpenLitUsageRecorder (NEW — OTLP spans to OpenLIT)
```

**Boot sequence changes in `setup_telemetry()`:**
1. Read `otlp_targets` from config (or fall back to single `otlp_endpoint`).
2. For each target, call `make_span_exporter(target)` → `BatchSpanProcessor`.
3. Add all processors to the shared `TracerProvider`.
4. Remove the `init_openlit()` call entirely.
5. Remove the Traceloop delegation path.

**Boot sequence changes in `ensure_observability_bootstrapped()`:**
1. Remove the `enable_traceloop` / `enable_openlit` branching.
2. The `"traceloop"` usage backend value is deprecated → maps to `"otel"`.
3. When `OBSERVABILITY_OPENLIT_RECORDER=true`, add `OpenLitUsageRecorder` to
   the recorder list in `build_recorders_from_config()`.

**`OpenLitUsageRecorder` internals:**
- On `__init__`: create a dedicated `TracerProvider` + `OTLPSpanExporter`
  pointing at the OpenLIT endpoint (separate from the main trace provider).
- On `record(UsageRecord)`: create a span named `"parrot.usage"` with GenAI
  SemConv attributes (`gen_ai.provider.name`, `gen_ai.request.model`,
  `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`,
  `gen_ai.usage.cost`, `gen_ai.operation.name`).
- On `aclose()`: call `TracerProvider.shutdown()` to flush the batch exporter.

### Edge Cases & Error Handling

- **Target endpoint unreachable:** `BatchSpanProcessor` handles this
  gracefully — it queues spans and retries on export. Export failures are
  logged but never propagate to the LLM call path.
- **All targets fail:** Telemetry degrades silently. LLM calls are unaffected.
  The OTel SDK's internal logging reports the failures.
- **Mixed old/new config:** When both `OTEL_EXPORTER_OTLP_ENDPOINT` and
  `OTLP_TARGETS` are set, `OTLP_TARGETS` wins. A warning is logged.
- **Deprecated env vars:** `OBSERVABILITY_OPENLIT=true` emits a
  `DeprecationWarning` once per process and is ignored. Same for
  `OBSERVABILITY_TRACELOOP=true`.
- **Recorder + trace pipeline overlap:** When both the OTel trace pipeline and
  the OpenLIT recorder target the same endpoint, the dashboard sees both trace
  spans and usage spans. These are correlated by `trace_id`. Documentation
  advises using the recorder alone for cost-only dashboards and the trace
  pipeline for full tracing.
- **Empty `otlp_targets` list:** Falls back to `otlp_endpoint` (backward compat).
  If both are empty, no exporters are created and a warning is logged.

---

## Capabilities

### New Capabilities
- `multi-endpoint-otlp`: Support N OTLP export targets in `setup_telemetry()` with shared protocol/sampling and per-target endpoint/headers
- `openlit-usage-recorder`: `AbstractLogger` backend that pushes `UsageRecord` data as GenAI SemConv OTel spans to an OpenLIT OTLP endpoint
- `openlit-bridge-package`: Lightweight `ai-parrot-openlit-bridge` package for endpoint validation and health checks

### Modified Capabilities
- `observability-config` (`parrot/observability/config.py`): Add `otlp_targets` model, deprecate `enable_openlit`/`enable_traceloop`
- `observability-setup` (`parrot/observability/setup.py`): Multi-processor TracerProvider, remove OpenLIT/Traceloop init
- `observability-exporters` (`parrot/observability/exporters.py`): Factory accepts target list
- `observability-bootstrap` (`parrot/observability/bootstrap.py`): Remove traceloop/openlit branching
- `genai-semconv-attributes` (`parrot/observability/attributes.py`): Add `gen_ai.operation.name`, rename cost attribute

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/observability/config.py` | modifies | Add `OtlpTarget` model, `otlp_targets` field, deprecate `enable_openlit`/`enable_traceloop` |
| `parrot/observability/setup.py` | modifies | Multi-BSP loop, remove `init_openlit()` call |
| `parrot/observability/exporters.py` | modifies | `make_span_exporter()` accepts `OtlpTarget`, new `make_span_exporters()` for multi-target |
| `parrot/observability/bootstrap.py` | modifies | Remove traceloop/openlit branching, add OpenLIT recorder |
| `parrot/observability/attributes.py` | modifies | Add `gen_ai.operation.name`, rename `parrot.cost.usd` → `gen_ai.usage.cost` |
| `parrot/observability/openlit_integration.py` | **deletes** | Replaced by pure OTLP export |
| `parrot/observability/traceloop_integration.py` | **deletes** | Replaced by pure OTLP export |
| `parrot/observability/recorders/factory.py` | modifies | Add `"openlit"` branch |
| `parrot/observability/recorders/` | new file | `openlit_recorder.py` — `OpenLitUsageRecorder` |
| `parrot/observability/__init__.py` | modifies | Remove traceloop imports, add new exports |
| `packages/ai-parrot/pyproject.toml` | modifies | Remove `openlit>=1.40.0` from extras, repurpose extra |
| `pyproject.toml` (workspace root) | modifies | Remove 11 `conflicting-groups` entries |
| `tests/` | new + modifies | Tests for multi-endpoint, recorder, deprecation warnings |

---

## Code Context

### User-Provided Code
_(No user-provided code snippets in this brainstorm.)_

### Verified Codebase References

#### Classes & Signatures
```python
# From parrot/observability/config.py:18
class ObservabilityConfig(BaseModel):
    enabled: bool = False                          # line 88
    otlp_endpoint: str = "http://localhost:4318"   # line 94
    otlp_protocol: Literal["http/protobuf", "grpc"] = "http/protobuf"  # line 95
    otlp_headers: dict[str, str] = Field(default_factory=dict)  # line 96
    enable_openlit: bool = False                   # line 102
    enable_traceloop: bool = False                 # line 103
    usage_backend: UsageBackend = "none"           # line 177
    # from_env() classmethod at line 183

# From parrot/observability/recorders/base.py:16
class AbstractLogger(ABC):
    name: str = "abstract"                         # line 28
    async def record(self, record: UsageRecord) -> None:  # line 30
    async def aclose(self) -> None:                # line 39

# From parrot/observability/recorders/models.py:31
class UsageRecord(BaseModel):
    provider: str
    client_name: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Optional[float] = None
    cumulative_cost_usd: Optional[float] = None
    duration_ms: float = 0.0
    finish_reason: Optional[str] = None
    trace_id: Optional[str] = None
    service_name: str = "ai-parrot"
    timestamp: datetime                            # line 74

# From parrot/observability/recorders/subscriber.py:30
class UsageRecordingSubscriber:
    def __init__(self, *, recorders: list[AbstractLogger], ...)  # line 40
    def register(self, registry: EventRegistry) -> None:        # line 63
    async def _on_client_after(self, event: AfterClientCallEvent):  # line 76

# From parrot/observability/subscribers/trace.py:59
class GenAIOpenTelemetrySubscriber:
    def __init__(self, *, service_name, tracer_provider, cost_calculator, capture_completions):  # line 78
    def register(self, registry: EventRegistry) -> None:  # line 107

# From parrot/observability/subscribers/metrics.py (line ~63)
class MetricsSubscriber:
    def __init__(self, *, meter_provider, service_name, histogram_buckets, cost_calculator):

# From parrot/observability/provider.py:28
class ParrotTelemetryProvider:
    def __init__(self, *, trace_subscriber, metrics_subscriber):  # line 43
    def register(self, registry: EventRegistry) -> None:         # line 52

# From parrot/observability/exporters.py
def make_span_exporter(config: ObservabilityConfig) -> Any:      # line 19
def make_metric_exporter(config: ObservabilityConfig) -> Any:    # line 63

# From parrot/observability/recorders/factory.py
def build_recorders_from_config(config: ObservabilityConfig) -> list[AbstractLogger]:  # line 23
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.observability.config import ObservabilityConfig  # config.py:18
from parrot.observability.recorders.base import AbstractLogger  # base.py:16
from parrot.observability.recorders.models import UsageRecord  # models.py:31
from parrot.observability.recorders.factory import build_recorders_from_config  # factory.py:23
from parrot.observability.recorders.subscriber import UsageRecordingSubscriber  # subscriber.py:30
from parrot.observability.attributes import resolve_gen_ai_system, build_after_client_attrs  # attributes.py
from parrot.observability.exporters import make_span_exporter, make_metric_exporter  # exporters.py
from parrot.observability.setup import setup_telemetry, shutdown_telemetry  # setup.py
from parrot.observability.provider import ParrotTelemetryProvider  # provider.py
from parrot.core.events.lifecycle.events import AfterClientCallEvent  # events/client.py:45
from navigator_eventbus import EventBus, Event, EventPriority  # navigator_eventbus
from navigator_eventbus.lifecycle.base import LifecycleEvent  # navigator_eventbus.lifecycle
```

#### Key Attributes & Constants
- `PROVIDER_TO_GEN_AI_SYSTEM` → `dict[str, str]` (`parrot/observability/attributes.py:34`) — maps client_name → gen_ai.system value
- `UsageBackend` → `Literal["none", "logging", "prometheus", "otel", "traceloop"]` (`parrot/observability/config.py:15`)
- `SemanticConvention.GEN_AI_PROVIDER_NAME` → `"gen_ai.provider.name"` (OpenLIT `semcov/__init__.py:174`)
- `SemanticConvention.GEN_AI_USAGE_COST` → `"gen_ai.usage.cost"` (OpenLIT vendor extension, `semcov/__init__.py:518`)
- `SemanticConvention.GEN_AI_SYSTEM_OPENAI` → `"openai"` (OpenLIT `semcov/__init__.py:308`)
- `SemanticConvention.GEN_AI_SYSTEM_ANTHROPIC` → `"anthropic"` (OpenLIT `semcov/__init__.py:297`)

#### OpenLIT SemConv Attribute Mapping (compatibility reference)
```python
# From openlit/semcov/__init__.py — these are the attributes the OpenLIT
# dashboard reads from OTLP spans. Our GenAIOpenTelemetrySubscriber must
# emit spans with these same attribute keys for dashboard compatibility.
"gen_ai.provider.name"          # TIER 1 — primary provider identifier (line 175)
"gen_ai.operation.name"         # TIER 1 — "chat", "embed", etc. (line 172)
"gen_ai.request.model"          # TIER 1 — model name on request (line 181)
"gen_ai.response.model"         # TIER 1 — model name on response (line 236)
"gen_ai.usage.input_tokens"     # TIER 3 — input token count (line 515)
"gen_ai.usage.output_tokens"    # TIER 3 — output token count (line 516)
"gen_ai.usage.cost"             # TIER 3 — OpenLIT vendor extension, USD cost (line 518)
"gen_ai.response.finish_reason" # standard OTel GenAI SemConv
"gen_ai.client.token.usage"     # metric name: histogram of token usage (line 96)
"gen_ai.client.operation.duration"  # metric name: histogram of call duration (line 97)
```

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.observability.exporters.make_span_exporters()`~~ — no multi-target factory exists; `make_span_exporter()` is singular
- ~~`parrot.observability.config.OtlpTarget`~~ — does not exist; must be created
- ~~`parrot.observability.config.ObservabilityConfig.otlp_targets`~~ — does not exist; must be added
- ~~`parrot.observability.recorders.openlit_recorder`~~ — does not exist; must be created
- ~~`CompositeSpanExporter`~~ — not a thing in OTel SDK; multi-target is done via multiple `BatchSpanProcessor` on one `TracerProvider`
- ~~`gen_ai.operation.name` in our attributes.py~~ — not emitted today; must be added
- ~~`gen_ai.usage.cost` in our attributes.py~~ — we use `parrot.cost.usd` instead; must be renamed/aliased
- ~~`ai-parrot-openlit-bridge` package~~ — does not exist; must be created (new package under `packages/`)
- ~~`OTLP_TARGETS` env var~~ — not read by `ObservabilityConfig.from_env()` today
- ~~`OBSERVABILITY_OPENLIT_RECORDER` env var~~ — not read today

---

## Parallelism Assessment

- **Internal parallelism**: Yes — tasks split cleanly into independent units:
  1. Config model changes (`OtlpTarget`, deprecations) — isolated to `config.py`
  2. Multi-endpoint exporter factory — isolated to `exporters.py`
  3. Attribute additions (`gen_ai.operation.name`, cost rename) — isolated to `attributes.py`
  4. `OpenLitUsageRecorder` — new file, depends only on `AbstractLogger` interface
  5. `setup_telemetry()` refactor — depends on (1) and (2)
  6. `bootstrap.py` cleanup — depends on (1) and (4)
  7. Delete `openlit_integration.py` + `traceloop_integration.py` — depends on (5) and (6)
  8. `pyproject.toml` cleanup — independent
  9. Bridge package — independent (new package)
  10. Tests — per-task

- **Cross-feature independence**: Low conflict risk. `parrot/observability/` is
  not actively modified by any in-flight feature. The only shared file is
  `pyproject.toml` (workspace root), which is always a merge-conflict risk but
  the changes are purely subtractive (removing `conflicting-groups`).

- **Recommended isolation**: `per-spec` — all tasks sequential in one worktree.

- **Rationale**: While tasks 1-4 are independent, they touch a tightly coupled
  module (`parrot/observability/`) where changes in one file affect imports and
  behavior in others. Sequential execution in one worktree avoids merge
  conflicts and ensures each task sees the previous task's changes. The total
  task count (~10) is manageable in a single worktree.

---

## Open Questions

- [x] Should OpenLIT and Traceloop be OTLP-only or keep SDK dependencies? — *Owner: Jesus*: Pure OTLP only. Drop both SDKs.
- [x] Multi-endpoint: native or external collector? — *Owner: Jesus*: Native multi-endpoint in `setup_telemetry()`.
- [x] Extras: remove, deprecate, or repurpose? — *Owner: Jesus*: Repurpose to install minimal bridge helper.
- [x] EventBus scope: now or future? — *Owner: Jesus*: Future only. Focus on pure OTLP (Option B) for this feature.
- [x] OpenLIT recorder: OTLP wrapper or REST API? — *Owner: Jesus*: OTLP exporter wrapper.
- [x] Per-target config granularity? — *Owner: Jesus*: Shared protocol/sampling/batch, per-target URL + headers.
- [x] Bridge package deps? — *Owner: Jesus*: Minimal helper (endpoint validation + health check CLI).
- [x] Does the OpenLIT dashboard correctly render GenAI SemConv spans that were NOT generated by the `openlit` SDK? — *Owner: Jesus*: Yes, confirmed. Standard GenAI SemConv OTLP spans render correctly.
- [x] Should the `gen_ai.usage.cost` attribute replace `parrot.cost.usd` entirely, or should we emit both for backward compatibility? — *Owner: Jesus*: Emit both — `gen_ai.usage.cost` (OpenLIT compat) and `parrot.cost.usd` (backward compat). The cost calculator writes both attributes on each span.
- [x] What is the minimum `ai-parrot-openlit-bridge` package scope? — *Owner: Jesus*: Three components: (1) `validate_endpoint(url)` — async probe that checks the OTLP endpoint is reachable and returns collector metadata; callable from `setup_telemetry()` at boot for early warning. (2) `parrot-openlit-check` CLI — wraps `validate_endpoint()` for operator use (`parrot-openlit-check http://openlit:4318`). (3) A bundled `docker-compose.openlit.yml` snippet for spinning up a local OpenLIT instance for dev/testing.
