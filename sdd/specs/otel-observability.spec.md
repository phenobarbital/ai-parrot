---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: OpenTelemetry + Cost Observability

**Feature ID**: FEAT-177
**Date**: 2026-05-18
**Author**: Jesus Lara
**Status**: draft
**Target version**: 1.x (minor release after FEAT-176)
**Source brainstorm**: `sdd/proposals/FEAT-177-otel-observability-brainstorm.md` (v0.2, 2026-05-15)
**Hard dependency**: FEAT-176 (Lifecycle Events System) — **already merged on `dev` as of 2026-05-16**

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot agents make LLM calls and tool executions that are currently observable only through ad-hoc logging. There is no standardized way to:

- Trace a single user invocation across agent → client → tool boundaries.
- Measure token usage, latency, and error rates per provider/model.
- Compute cost per request / per user / per agent in USD.
- Export the data to industry-standard observability backends (Jaeger, Tempo, Prometheus, Grafana, OpenLIT UI).

FEAT-176 (merged 2026-05-16) shipped the **plumbing** — typed lifecycle events, `EventRegistry`, `TraceContext` (W3C), `EventProvider` Protocol, and a **minimal** `OpenTelemetrySubscriber` stub. What is missing is the **semantic layer** on top:

1. A GenAI-SemConv-compliant span subscriber with full attribute coverage.
2. A separate metrics subscriber (counters + histograms).
3. A cost-tracking pipeline (pricing tables + calculator + cost metric).
4. A boot helper that wires it all up from `navconfig` env vars.
5. Optional opt-in OpenLIT auto-instrumentation for SDK-level child spans.

This feature ships that semantic layer as `parrot.observability`.

### Goals

- Provide a one-call boot helper `setup_telemetry(ObservabilityConfig)` that wires spans, metrics, and cost tracking against the FEAT-176 lifecycle events.
- Emit GenAI Semantic Conventions–compliant spans for every LLM call and tool execution.
- Emit OTel metrics (counters/histograms) for tokens, latency, errors, and cost.
- Track cost in USD via bundled pricing tables per provider, with a `PARROT_PRICING_PATH` override hook.
- Keep hot-path overhead under ~200 μs per request (≪ 0.1% of LLM latency) when telemetry is enabled.
- Keep hot-path overhead at the dataclass-construction floor (~5 ns per event) when telemetry is disabled.
- Patch FEAT-176's `EventRegistry.emit` so per-subscriber `forward_to_bus=True` dispatches via `asyncio.create_task(...)` instead of blocking `await` — without this patch the §5 performance budget is unenforceable.

### Non-Goals (explicitly out of scope)

- Anything FEAT-176 already does (event emission, mixins, lifecycle hooks, `TraceContext` propagation).
- Agent-level instrumentation beyond what FEAT-176's events expose (no separate `BotManager` spans — those come from `BeforeInvokeEvent`).
- MCP tool instrumentation (deferred — separate FEAT).
- Vector store / RAG instrumentation (deferred — separate FEAT).
- Loader observability (deferred — separate FEAT).
- Interceptor-based instrumentation (out of scope until FEAT-176 Phase 2).
- Custom dashboards / Grafana JSON layouts beyond a single starter dashboard.
- Per-agent telemetry config (deferred to a future minor — Phase 1 is global-only).
- Default PII redactor for prompts/completions (kept pluggable; shipping no default — see D3 below).
- A separate `TelemetryMixin` on `AbstractClient` (rejected — FEAT-176's `EventEmitterMixin` already covers emission; see brainstorm §1.2).

---

## 2. Architectural Design

### Overview

`parrot.observability` is a new top-level subpackage that registers **three subscribers** against FEAT-176's `global_registry` via a single bundling `EventProvider`:

1. `GenAIOpenTelemetrySubscriber` — opens/closes OTel spans for invoke/client/tool events, attaches GenAI SemConv attributes.
2. `MetricsSubscriber` — emits OTel counters and histograms for tokens, latency, errors, and cost.
3. (Optional) `CostCalculator` — pure function called by the two subscribers above; loads bundled JSON pricing tables once at import time.

A single `setup_telemetry(ObservabilityConfig)` boot helper configures the OTel `TracerProvider` / `MeterProvider`, instantiates the subscribers, bundles them into a `ParrotTelemetryProvider` (implementing FEAT-176's `EventProvider` Protocol), and calls `get_global_registry().add_provider(...)`. Idempotent on re-call.

Optionally, when `enable_openlit=True`, the helper lazy-imports `openlit` and calls `openlit.init(...)` so SDK-level HTTP calls (OpenAI/Anthropic/etc.) auto-create OTel child spans under our parent spans.

### Component Diagram

```
                    setup_telemetry(ObservabilityConfig)
                                 │
                ┌────────────────┼─────────────────┐
                │                │                 │
        TracerProvider   MeterProvider     OpenLIT (opt-in)
        (BatchSpanProc)  (PeriodicReader)
                │                │
                └────────┬───────┘
                         │ used by
                         ▼
              ParrotTelemetryProvider
              (implements EventProvider)
                         │
        ┌────────────────┼─────────────────┐
        │                │                 │
  GenAIOTelSub    MetricsSubscriber   CostCalculator
        │                │                 │
        └────────┬───────┘                 │
                 │ register()              │
                 ▼                         │
       global_registry (FEAT-176) ◀────────┘ used by both
                 │
                 └── receives Before/After/Failed events ──▶ exporters
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `EventRegistry` (FEAT-176) | **patches** | TASK-000 wraps per-subscriber bus dispatch in `asyncio.create_task(...)`. |
| `get_global_registry()` (FEAT-176) | **uses** | `setup_telemetry()` calls `.add_provider(ParrotTelemetryProvider())`. |
| `EventProvider` Protocol (FEAT-176) | **implements** | `ParrotTelemetryProvider.register(registry)` registers all three subscribers. |
| `LifecycleEvent` subclasses (FEAT-176) | **subscribes** | 12 of the 15 event classes (see §3 Event → Span mapping). |
| `TraceContext` (FEAT-176) | **consumes** | Reads `trace_id`/`span_id`/`parent_span_id` to build OTel `SpanContext`. |
| `OpenTelemetrySubscriber` (FEAT-176 stub) | **coexists** | Not modified, not removed. Different class name (`GenAIOpenTelemetrySubscriber`) — users select via config. |
| `CompletionUsage.estimated_cost` (`parrot/models/basic.py:57`) | **populates** | `CostCalculator.cost_usd()` result is written back via the new subscribers (no model changes). |
| `AbstractClient.client_name` (`parrot/clients/base.py:248-249`) | **reads** | Source for `gen_ai.system` attribute via the `client_name` field on `BeforeClientCallEvent`. |
| `navconfig.config` | **uses** | All env vars read via `config.get(...)`, `config.getboolean(...)`, `config.getfloat(...)`. |

### Data Models

```python
# parrot/observability/config.py
from pydantic import BaseModel, Field
from typing import Optional, Literal

class ObservabilityConfig(BaseModel):
    """Single global configuration for the parrot.observability stack."""

    enabled: bool = False
    service_name: str = "ai-parrot"
    service_version: Optional[str] = None
    service_instance_id: Optional[str] = None  # default: hostname-pid

    # Exporter
    otlp_endpoint: str = "http://localhost:4318"
    otlp_protocol: Literal["http/protobuf", "grpc"] = "http/protobuf"
    otlp_headers: dict[str, str] = Field(default_factory=dict)

    # Subscribers
    enable_traces: bool = True
    enable_metrics: bool = True
    enable_cost_tracking: bool = True
    enable_openlit: bool = False

    # Sampling & PII
    sampling_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    capture_prompts: bool = False        # PII: default off
    capture_completions: bool = False    # PII: default off

    # Metric export tuning
    metric_export_interval_ms: int = 60_000
    histogram_buckets: Optional[list[float]] = None  # None → LLM-tuned defaults

    # Cost pricing override (mirrors PARROT_PRICING_PATH env var)
    pricing_override_path: Optional[str] = None
```

### New Public Interfaces

```python
# parrot/observability/__init__.py
from parrot.observability.config import ObservabilityConfig
from parrot.observability.setup import setup_telemetry, shutdown_telemetry
from parrot.observability.subscribers.trace import GenAIOpenTelemetrySubscriber
from parrot.observability.subscribers.metrics import MetricsSubscriber
from parrot.observability.cost.calculator import CostCalculator
from parrot.observability.provider import ParrotTelemetryProvider

__all__ = [
    "ObservabilityConfig",
    "setup_telemetry",
    "shutdown_telemetry",
    "GenAIOpenTelemetrySubscriber",
    "MetricsSubscriber",
    "CostCalculator",
    "ParrotTelemetryProvider",
]


# parrot/observability/setup.py
def setup_telemetry(config: ObservabilityConfig) -> "ParrotTelemetryProvider | None":
    """Configure tracer/meter providers and register subscribers.

    Idempotent: subsequent calls with the same config are no-ops; calls with
    a different config raise ConfigurationError.

    Returns:
        The registered provider (for `shutdown_telemetry`), or None when
        ``config.enabled is False``.
    """


def shutdown_telemetry() -> None:
    """Flush exporters and unregister subscribers. Idempotent."""
```

### Event → Span mapping (carried forward from brainstorm §4.4)

| FEAT-176 Event | OTel action | Span name | Notes |
|---|---|---|---|
| `BeforeInvokeEvent` | Start root span | `parrot.agent.invoke` | Honours `event.trace_context` |
| `AfterInvokeEvent` | End span; `Status.OK` | — | Attach final usage attrs |
| `InvokeFailedEvent` | End span; `Status.ERROR` | — | `span.record_exception` |
| `BeforeClientCallEvent` | Start child span | `parrot.client.<provider>.<operation>` | Sets `gen_ai.system`, `gen_ai.request.model`, `gen_ai.request.temperature`, `parrot.system_prompt_hash`, `gen_ai.request.has_tools` |
| `AfterClientCallEvent` | End span; OK | — | Attach `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.response.finish_reason`, `parrot.cost.usd` |
| `ClientCallFailedEvent` | End span; ERROR | — | `error.type`, `error.message` |
| `ClientStreamChunkEvent` | Optional span event (only if `capture_completions=True`) | — | NEVER updates metrics, NEVER triggers exporter flush |
| `BeforeToolCallEvent` | Start child span | `parrot.tool.<name>` | `parrot.tool.name`, `parrot.tool.class` |
| `AfterToolCallEvent` | End span; OK | — | `parrot.tool.result.status`, `parrot.tool.result.size_bytes` |
| `ToolCallFailedEvent` | End span; ERROR | — | `error.type`, `error.message` |
| `MessageAddedEvent` | Span event on parent invoke span | — | `parrot.message.role`, `parrot.message.content_length` |
| `AgentStatusChangedEvent` | Span event on active span | — | — |
| `AgentInitializedEvent`, `AgentConfiguredEvent`, `ToolManagerReadyEvent` | Log only (no spans) | — | Boot-time |
| `SubscriberErrorEvent` | Log at WARNING; NEVER create a span | — | Avoid recursion |

### Event → Metric mapping (carried forward from brainstorm §4.5)

| Event | Metric | Type | Attributes (whitelist) |
|---|---|---|---|
| `BeforeClientCallEvent` | `gen_ai.client.request.count` | Counter | `gen_ai.system`, `gen_ai.request.model` |
| `AfterClientCallEvent` | `gen_ai.client.operation.duration` | Histogram | `gen_ai.system`, `gen_ai.operation.name` |
| `AfterClientCallEvent` | `gen_ai.client.token.usage` | Histogram | `gen_ai.system`, `gen_ai.response.model`, `gen_ai.token.type` (`input`/`output`) |
| `AfterClientCallEvent` | `gen_ai.client.cost.total` | Counter (USD) | `gen_ai.system`, `gen_ai.response.model` |
| `ClientCallFailedEvent` | `gen_ai.client.error.count` | Counter | `gen_ai.system`, `error.type` |
| `AfterToolCallEvent` | `parrot.tool.execution.duration` | Histogram | `parrot.tool.name` |
| `ToolCallFailedEvent` | `parrot.tool.failure.count` | Counter | `parrot.tool.name`, `error.type` |
| `AfterInvokeEvent` | `parrot.agent.invoke.duration` | Histogram | `parrot.agent.name`, `parrot.invoke.method` |
| `InvokeFailedEvent` | `parrot.agent.invoke.failure.count` | Counter | `parrot.agent.name`, `error.type` |

**Cardinality guard**: an explicit attribute whitelist per metric. `user_id`, `session_id`, and raw text never appear in metric labels.

### Provider → `gen_ai.system` mapping (verified against `parrot/clients/*.py`)

| `client_name` emitted on `BeforeClientCallEvent` | Source | `gen_ai.system` value |
|---|---|---|
| `"openai"` | `parrot/clients/gpt.py:182,201,778,…` | `openai` |
| `"anthropic"` | `parrot/clients/claude.py:162,179,239,…` | `anthropic` |
| `"claude-agent"` | `parrot/clients/claude_agent.py:468,491,608,…` | `anthropic` |
| `"google"` | `parrot/clients/google/client.py:1860,2538,2677,…` | `gemini` (default) — override via `ObservabilityConfig` table when running on Vertex |
| `"gemini-live"` | `parrot/clients/live.py:1111,1253,1269` | `gemini` |
| `"groq"` | `parrot/clients/groq.py:300,609,654,…` | `groq` |
| `"grok"` | `parrot/clients/grok.py:229,417,454,…` | `xai` (no OTel-standard value — use custom) |
| `"nvidia"` | `parrot/clients/nvidia.py:70-71` | `nvidia` (custom — no OTel-standard value) |
| `"huggingface"` | `parrot/clients/hf.py:392,505` | `huggingface` (custom) |
| `"gemma4"` | `parrot/clients/gemma4.py:511,648` | `huggingface` (Gemma is HF-hosted) |

Mapping table lives in `parrot/observability/attributes.py` so it is a single point of update when OTel SemConv adds new standard values.

---

## 3. Module Breakdown

> **TASK-000 is the patch task and blocks every other module.**

### TASK-000: Patch `EventRegistry.emit` — fire-and-forget bus dispatch
- **Path**: `parrot/core/events/lifecycle/registry.py` (lines 276-281)
- **Responsibility**: Wrap per-subscriber `EventBus` dispatch in `asyncio.create_task(...)` so a slow Redis bus never blocks the agent's request path.
- **Why this is a FEAT-177 task, not a FEAT-176 fix**: The brainstorm §2.1 explicitly anticipated this exact patch as the contingency if FEAT-176 didn't ship fire-and-forget. The audit (2026-05-18) confirmed FEAT-176 shipped blocking `await self._event_bus.emit(...)`. The patch is small and self-contained, so it lives in this feature's first task.
- **Depends on**: nothing.
- **Blocks**: every other module.

### Module 1: `ObservabilityConfig` + module skeleton
- **Path**: `parrot/observability/__init__.py`, `parrot/observability/config.py`
- **Responsibility**: Pydantic v2 config model + public re-exports.
- **Depends on**: TASK-000.

### Module 2: GenAI SemConv attribute builders
- **Path**: `parrot/observability/attributes.py`
- **Responsibility**: Pure functions that map a lifecycle event to a dict of OTel attributes. Centralizes the provider → `gen_ai.system` table. Single update point if OTel SemConv renames an attribute.
- **Depends on**: Module 1.

### Module 3: `GenAIOpenTelemetrySubscriber`
- **Path**: `parrot/observability/subscribers/trace.py`
- **Responsibility**: Maps the 12 relevant `LifecycleEvent` classes to OTel spans (see §2 Event → Span mapping). Holds an `asyncio.Lock`-guarded `_active_spans: dict[str, Span]` keyed by `trace_context.span_id`. Implements `register(registry)` per `EventProvider` Protocol.
- **Depends on**: Module 2.

### Module 4: `MetricsSubscriber`
- **Path**: `parrot/observability/subscribers/metrics.py`
- **Responsibility**: Maps events to OTel counters/histograms (see §2 Event → Metric mapping). Enforces cardinality whitelist. Default histogram buckets `[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0, 60.0]` seconds, overridable via `ObservabilityConfig.histogram_buckets`.
- **Depends on**: Module 2.

### Module 5: `CostCalculator` + bundled pricing JSON
- **Path**: `parrot/observability/cost/calculator.py`, `parrot/observability/cost/pricing/{openai,anthropic,google,groq,nvidia}.json`
- **Responsibility**: Stateless calculator; pricing tables loaded once at import. Returns `None` for unknown `(provider, model)` pairs and logs a `WARN` once per pair. Resolves overrides via `ObservabilityConfig.pricing_override_path` (default sourced from `PARROT_PRICING_PATH` env var via navconfig). Each JSON file carries a `pricing.last_updated` field; calculator logs a warning at boot if cached pricing is older than 90 days.
- **Depends on**: Module 1.

### Module 6: `ParrotTelemetryProvider`
- **Path**: `parrot/observability/provider.py`
- **Responsibility**: Implements FEAT-176's `EventProvider` Protocol. Bundles the three subscribers; `register(registry)` calls each subscriber's `register`.
- **Depends on**: Modules 3, 4, 5.

### Module 7: OTLP exporter helpers
- **Path**: `parrot/observability/exporters.py`
- **Responsibility**: Factory functions returning `OTLPSpanExporter` and `OTLPMetricExporter` for `http/protobuf` or `grpc`. Reads endpoint, headers, and protocol from `ObservabilityConfig`.
- **Depends on**: Module 1.

### Module 8: `setup_telemetry()` boot helper
- **Path**: `parrot/observability/setup.py`
- **Responsibility**: Idempotent boot:
  1. If `config.enabled is False`, return `None` immediately (no-op).
  2. Build `Resource` with `service.name`, `service.version`, `service.instance.id = f"{socket.gethostname()}-{os.getpid()}"`, `parrot.version`.
  3. Configure `TracerProvider` with `BatchSpanProcessor` (Simple is forbidden — raise `ConfigurationError` if detected) + `TraceIdRatioBased(config.sampling_ratio)`.
  4. Configure `MeterProvider` with `PeriodicExportingMetricReader(interval=config.metric_export_interval_ms)`.
  5. Build `CostCalculator` if `enable_cost_tracking`.
  6. Build `GenAIOpenTelemetrySubscriber` + `MetricsSubscriber`, wrap in `ParrotTelemetryProvider`, call `get_global_registry().add_provider(provider)`.
  7. If `enable_openlit`, lazy-import `openlit` and call `openlit.init(otlp_endpoint=..., application_name=...)`. Module-level sentinel prevents double-init.
  8. Return the provider handle.
- **Depends on**: Modules 1, 2, 3, 4, 5, 6, 7.

### Module 9: OpenLIT integration wrapper
- **Path**: `parrot/observability/openlit_integration.py`
- **Responsibility**: Lazy-imported wrapper around `openlit.init(...)`. Idempotency sentinel. Documents the parent-span contract (OpenLIT auto-spans become children of our spans).
- **Depends on**: Module 8 calls it.

### Module 10: Examples + docker-compose
- **Path**: `parrot/observability/examples/docker-compose.observability.yml`, `parrot/observability/examples/basic_telemetry.py`, `parrot/observability/examples/grafana-dashboards/parrot-overview.json`
- **Responsibility**: Runnable end-to-end demo with one observability stack (OpenLIT UI default per D4).
- **Depends on**: Module 8.

### Module 11: README + end-to-end PoC
- **Path**: `parrot/observability/README.md`, `tests/integration/observability/test_poc.py`
- **Responsibility**: Documentation + a 5-scenario PoC analogous to FEAT-176 Module 18: traces-only, metrics-only, with cost, with OpenLIT, with sampling.
- **Depends on**: All prior modules.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_emit_bus_dispatch_is_fire_and_forget` | TASK-000 | A fake `EventBus` whose `emit` blocks on an `asyncio.Event` is forwarded via `forward_to_bus=True`; `EventRegistry.emit` must return without waiting. Asserts via `asyncio.wait_for(emit, timeout=0.1)` plus a sentinel proving the bus task is scheduled. |
| `test_emit_bus_exception_does_not_break_emit` | TASK-000 | Fake bus raises in `emit`; `EventRegistry.emit` still completes; exception logged. |
| `test_config_defaults` | Module 1 | `ObservabilityConfig()` has `enabled=False`, `capture_prompts=False`, `capture_completions=False`, `sampling_ratio=1.0`. |
| `test_config_rejects_invalid_sampling` | Module 1 | `sampling_ratio=1.5` raises `ValidationError`. |
| `test_attribute_builder_before_client` | Module 2 | `build_before_client_attrs(BeforeClientCallEvent(client_name="openai", model="gpt-4o", ...))` returns dict with `gen_ai.system="openai"`, `gen_ai.request.model="gpt-4o"`, no PII. |
| `test_provider_to_gen_ai_system_mapping` | Module 2 | Every `client_name` listed in §2 table maps to its expected `gen_ai.system` value. |
| `test_trace_subscriber_creates_span_per_request` | Module 3 | With `InMemorySpanExporter`: emit Before/AfterInvokeEvent + Before/AfterClientCallEvent + Before/AfterToolCallEvent → exactly 3 spans with correct parent-child chain. |
| `test_trace_subscriber_error_path` | Module 3 | `ClientCallFailedEvent` ends span with `StatusCode.ERROR` and records exception attrs. |
| `test_trace_subscriber_streaming_default_skips_chunks` | Module 3 | `ClientStreamChunkEvent` with `capture_completions=False` does NOT add a span event. |
| `test_trace_subscriber_streaming_opt_in_adds_event` | Module 3 | Same event with `capture_completions=True` adds one span event per chunk. |
| `test_metrics_subscriber_counters_and_histograms` | Module 4 | With `InMemoryMetricReader`: emit one full request cycle → `gen_ai.client.request.count == 1`, `gen_ai.client.token.usage` histogram has 2 records (input+output). |
| `test_metrics_subscriber_cardinality_whitelist` | Module 4 | Extra fields on event (`session_id`, `user_id`) MUST NOT appear in any metric label set. |
| `test_metrics_default_buckets_are_llm_tuned` | Module 4 | Default `histogram_buckets == [0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0, 60.0]`. |
| `test_cost_known_model` | Module 5 | `CostCalculator.cost_usd(provider="openai", model="gpt-4o-2024-08-06", input_tokens=1000, output_tokens=500) == 0.0075` (using stub pricing 2.50/10.00 per 1M). |
| `test_cost_unknown_model_returns_none_and_warns_once` | Module 5 | Unknown model returns `None`; logger emits WARN once even after 100 calls. |
| `test_cost_override_path` | Module 5 | `ObservabilityConfig(pricing_override_path=tmp)` deep-merges files in `tmp/` over bundled pricing. |
| `test_cost_stale_warning` | Module 5 | Pricing file with `last_updated` > 90 days ago triggers a WARN at boot. |
| `test_provider_registers_three_subscribers` | Module 6 | `ParrotTelemetryProvider().register(reg)` → `len(reg._subscriptions) >= 12` (trace+metrics share events but each subscribes independently). |
| `test_exporter_factory_http_vs_grpc` | Module 7 | `make_span_exporter(config, protocol="grpc")` returns gRPC variant; default returns HTTP. |
| `test_setup_idempotent_same_config` | Module 8 | Two consecutive `setup_telemetry(cfg)` calls return the same provider instance; only one subscriber set registered. |
| `test_setup_conflicting_config_raises` | Module 8 | Second call with different `service_name` raises `ConfigurationError`. |
| `test_setup_disabled_is_no_op` | Module 8 | `setup_telemetry(ObservabilityConfig(enabled=False))` returns `None`; `get_global_registry()._subscriptions` is empty. |
| `test_setup_forbids_simple_span_processor` | Module 8 | Monkey-patched config that swaps in `SimpleSpanProcessor` raises `ConfigurationError`. |
| `test_setup_service_instance_id_default` | Module 8 | When `config.service_instance_id is None`, the registered `Resource` has `service.instance.id == f"{gethostname()}-{getpid()}"`. |
| `test_openlit_lazy_import_when_disabled` | Module 9 | With `enable_openlit=False`, `openlit` module is never imported (verify via `sys.modules`). |
| `test_openlit_init_idempotent` | Module 9 | Two calls with `enable_openlit=True` invoke `openlit.init` exactly once. |

### Integration Tests

| Test | Description |
|---|---|
| `test_end_to_end_real_agent_one_call` | Configure with `InMemorySpanExporter` + `InMemoryMetricReader`; run a real `Chatbot.ask()` against a mock client; assert 1 root span + 1 client span + N tool spans + matching metrics + non-None cost. |
| `test_openlit_does_not_double_count` | With OpenLIT enabled against a mock OpenAI HTTP server, assert exactly one parent span per `ask()` and that OpenLIT's HTTP span is a child, not a sibling. |
| `test_perf_overhead_disabled` | Baseline: `bot.ask()` with telemetry disabled. Median p50 over 100 runs is the baseline. |
| `test_perf_overhead_enabled` | Same run with telemetry enabled (BatchSpanProcessor, no OpenLIT). p50 delta < 1 ms vs baseline. |
| `test_perf_overhead_with_openlit` | Same run with OpenLIT. p50 delta < 5 ms vs baseline. |
| `test_poc_five_scenarios` | Runnable PoC script (Module 11): traces-only, metrics-only, with cost, with OpenLIT, with sampling=0.1. Each prints the expected exporter output for manual eyeballing in CI logs. |

### Test Data / Fixtures

```python
@pytest.fixture
def in_memory_telemetry():
    """Returns (span_exporter, metric_reader) backed by InMemory* and wired
    into a fresh global_registry via scope()."""
    ...

@pytest.fixture
def stub_pricing(tmp_path):
    """Writes a known-value pricing/openai.json into tmp_path for override
    testing."""
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass: `pytest tests/unit/observability/ -v`
- [ ] All integration tests pass: `pytest tests/integration/observability/ -v`
- [ ] **TASK-000 patch in place**: `EventRegistry.emit` dispatches per-subscriber bus forward via `asyncio.create_task(...)`. `test_emit_bus_dispatch_is_fire_and_forget` proves a blocking bus does not delay `emit()`.
- [ ] `setup_telemetry(ObservabilityConfig())` with defaults is a true no-op (returns `None`, registers nothing).
- [ ] `setup_telemetry(ObservabilityConfig(enabled=True))` produces spans matching the §2 Event → Span mapping for a full `bot.ask()` cycle (verified via `InMemorySpanExporter`).
- [ ] Performance budget: with telemetry enabled, p50 overhead on a real `bot.ask()` is **< 1 ms** vs the disabled baseline; with OpenLIT, **< 5 ms**. Hard fail otherwise.
- [ ] `SimpleSpanProcessor` is forbidden — `setup_telemetry` raises `ConfigurationError` if it is configured.
- [ ] Cardinality whitelist enforced — `user_id`, `session_id`, and prompt/completion content NEVER appear on metric labels.
- [ ] PII default: `capture_prompts=False`, `capture_completions=False`. Acceptance test asserts no prompt text leaves the subscriber when defaults are kept.
- [ ] Cost: `CostCalculator` returns USD for every bundled provider/model present in `pricing/*.json`; returns `None` and logs once per unknown `(provider, model)` pair.
- [ ] Pricing override: setting `PARROT_PRICING_PATH` (or `pricing_override_path`) to a directory deep-merges its JSONs over bundled pricing.
- [ ] OpenLIT is optional — installable via `pip install 'ai-parrot[observability-openlit]'`. When not installed, `enable_openlit=True` raises `ImportError` with a clear action message; `enable_openlit=False` does not import `openlit`.
- [ ] `parrot.observability.README.md` documents the env vars, the navconfig keys, the PII contract, and the PoC script.
- [ ] PoC (Module 11) runs end-to-end in CI for all 5 scenarios.
- [ ] No breaking changes to existing public API. FEAT-176's `OpenTelemetrySubscriber` is left untouched and continues to work.

---

## 6. Codebase Contract

> Anti-Hallucination Anchor — every reference below verified against the working tree on `dev` at HEAD on 2026-05-18.

### Verified Imports

```python
# All verified to resolve via __init__.py exports or direct module path.

# FEAT-176 — Lifecycle Events System (the foundation)
from parrot.core.events.lifecycle.registry import EventRegistry            # registry.py:1
from parrot.core.events.lifecycle.global_registry import (
    get_global_registry, scope,                                            # global_registry.py:37,58
)
from parrot.core.events.lifecycle.provider import EventProvider             # provider.py:19
from parrot.core.events.lifecycle.trace import TraceContext                 # trace.py:14
from parrot.core.events.lifecycle.base import LifecycleEvent                # base.py (subclass parent)
from parrot.core.events.lifecycle.meta import SubscriberErrorEvent          # meta.py:14

# Event classes (FEAT-176, all 14 used by FEAT-177; +1 meta event)
from parrot.core.events.lifecycle.events import (                           # events/__init__.py
    BeforeInvokeEvent, AfterInvokeEvent, InvokeFailedEvent,                 # events/invoke.py:13,33,54
    BeforeClientCallEvent, AfterClientCallEvent, ClientCallFailedEvent,     # events/client.py:17,37,61
    ClientStreamChunkEvent,                                                 # events/client.py:82
    BeforeToolCallEvent, AfterToolCallEvent, ToolCallFailedEvent,           # events/tool.py:11,29,48
    MessageAddedEvent,                                                      # events/message.py:11
    AgentInitializedEvent, AgentConfiguredEvent,                            # events/agent.py:14,27
    ToolManagerReadyEvent, AgentStatusChangedEvent,                         # events/agent.py:44,59
)

# FEAT-176's stub OTel subscriber (coexists, not modified)
from parrot.core.events.lifecycle.subscribers.opentelemetry import (        # subscribers/opentelemetry.py:39
    OpenTelemetrySubscriber,
)

# Models
from parrot.models.basic import CompletionUsage                              # models/basic.py (estimated_cost at line 57)
from parrot.models.responses import AIMessage                                # models/responses.py

# Tools
from parrot.tools.abstract import AbstractTool                               # tools/abstract.py (permission_context at 462; trace_context at 501)
from parrot.tools.toolkit import AbstractToolkit                             # tools/toolkit.py (_pre_execute at 284; _post_execute at 187)
```

### Existing Class Signatures (the spec depends on these — verified verbatim)

```python
# parrot/core/events/lifecycle/registry.py
class EventRegistry:
    """FEAT-176 §3 — central dispatch engine for typed LifecycleEvent."""

    # line 246-285 — emit() dispatch loop
    async def emit(self, event: LifecycleEvent) -> None: ...

    # line 276-281 — CURRENT (blocking) per-subscriber dual-emit. TASK-000 patches.
    # if sub.forward_to_bus and self._event_bus is not None:
    #     channel = f"{self._bus_channel_prefix}.{cls_name}"
    #     try:
    #         await self._event_bus.emit(channel, event.to_dict())
    #     except Exception:
    #         logger.exception("Dual-emit to EventBus failed for channel %s", channel)

    # line 287-308 — meta-event dispatch with recursion guard via _emitting_meta ContextVar
    async def _emit_meta(self, event: LifecycleEvent) -> None: ...

    # add_provider(provider) → list[str] of subscription IDs (verified via provider.py docstring at line 36-37)
    def add_provider(self, provider: "EventProvider") -> list[str]: ...

# parrot/core/events/lifecycle/provider.py:19-51
@runtime_checkable
class EventProvider(Protocol):
    def register(self, registry: "EventRegistry") -> None: ...     # line 45 — MUST be synchronous

# parrot/core/events/lifecycle/global_registry.py
def get_global_registry() -> EventRegistry: ...    # line 37, lazy-singleton; forward_to_global=False
@contextmanager
def scope() -> Iterator[EventRegistry]: ...        # line 58, ContextVar token/reset isolation

# parrot/core/events/lifecycle/trace.py
@dataclass(frozen=True)
class TraceContext:                                    # line 14
    trace_id: str                                      # line 38 — 32 hex chars
    span_id: str                                       # line 39 — 16 hex chars
    trace_flags: int = 1                               # line 40
    trace_state: str = ""                              # line 41
    parent_span_id: Optional[str] = None               # line 42
    @classmethod
    def new_root(cls) -> "TraceContext": ...           # line 44
    def child(self) -> "TraceContext": ...             # line 62
    @classmethod
    def from_traceparent_header(cls, header: str) -> "TraceContext": ...   # line 90
    def to_traceparent_header(self) -> str: ...        # line 161
    def to_dict(self) -> dict: ...                     # line 177
    @classmethod
    def from_dict(cls, data: dict) -> "TraceContext": ...   # line 197

# parrot/core/events/lifecycle/events/client.py
@dataclass(frozen=True)
class BeforeClientCallEvent(LifecycleEvent):           # line 17
    client_name: str = ""                              # line 30
    model: str = ""                                    # line 31
    temperature: Optional[float] = None                # line 32
    system_prompt_hash: str = ""                       # line 33 — SHA-256, never raw text
    has_tools: bool = False                            # line 34

@dataclass(frozen=True)
class AfterClientCallEvent(LifecycleEvent):            # line 37
    client_name: str = ""                              # line 53
    model: str = ""                                    # line 54
    duration_ms: float = 0.0                           # line 55
    input_tokens: Optional[int] = None                 # line 56
    output_tokens: Optional[int] = None                # line 57
    finish_reason: Optional[str] = None                # line 58

@dataclass(frozen=True)
class ClientCallFailedEvent(LifecycleEvent):           # line 61
    client_name: str                                   # line 75
    model: str                                         # line 76
    duration_ms: float                                 # line 77
    error_type: str                                    # line 78
    error_message: str                                 # line 79

@dataclass(frozen=True)
class ClientStreamChunkEvent(LifecycleEvent):          # line 82
    client_name: str                                   # line 100
    model: str                                         # line 101
    chunk_index: int                                   # line 102
    chunk_size_bytes: int                              # line 103

# parrot/core/events/lifecycle/events/tool.py
@dataclass(frozen=True)
class BeforeToolCallEvent(LifecycleEvent):             # line 11
    tool_name: str                                     # line 24
    tool_class: str                                    # line 25
    args_summary: dict                                 # line 26 — already truncated at emission site

@dataclass(frozen=True)
class AfterToolCallEvent(LifecycleEvent):              # line 29
    tool_name: str                                     # line 42
    duration_ms: float                                 # line 43
    result_status: str                                 # line 44 — "success" | "partial"
    result_size_bytes: int                             # line 45

@dataclass(frozen=True)
class ToolCallFailedEvent(LifecycleEvent):             # line 48
    tool_name: str                                     # line 61
    duration_ms: float                                 # line 62
    error_type: str                                    # line 63
    error_message: str                                 # line 64

# parrot/core/events/lifecycle/events/invoke.py
@dataclass(frozen=True)
class BeforeInvokeEvent(LifecycleEvent):               # line 13
    agent_name: str; method: str; question: str        # lines 26-28
    user_id: Optional[str]; session_id: Optional[str]   # lines 29-30

@dataclass(frozen=True)
class AfterInvokeEvent(LifecycleEvent):                # line 33
    agent_name: str; method: str; duration_ms: float   # lines 47-49
    input_tokens: Optional[int]; output_tokens: Optional[int]   # lines 50-51

@dataclass(frozen=True)
class InvokeFailedEvent(LifecycleEvent):               # line 54
    agent_name: str; method: str; duration_ms: float   # lines 68-70
    error_type: str; error_message: str                # lines 71-72

# parrot/core/events/lifecycle/events/agent.py
@dataclass(frozen=True)
class AgentInitializedEvent(LifecycleEvent):           # line 14
    agent_name: str; agent_class: str                  # lines 23-24

@dataclass(frozen=True)
class AgentConfiguredEvent(LifecycleEvent):            # line 27
    agent_name: str; llm_provider: str; llm_model: str # lines 38-40
    has_vector_store: bool                              # line 41

@dataclass(frozen=True)
class ToolManagerReadyEvent(LifecycleEvent):           # line 44
    agent_name: str; tool_count: int; tool_names: tuple # lines 54-56

@dataclass(frozen=True)
class AgentStatusChangedEvent(LifecycleEvent):         # line 59
    agent_name: str; old_status: str; new_status: str  # lines 73-75

# parrot/core/events/lifecycle/events/message.py
@dataclass(frozen=True)
class MessageAddedEvent(LifecycleEvent):               # line 11
    agent_name: str                                    # line 27
    role: str                                          # line 28 — "user"|"assistant"|"tool"|"system"
    content_length: int                                # line 29
    has_tool_calls: bool                               # line 30

# parrot/core/events/lifecycle/meta.py
@dataclass(frozen=True)
class SubscriberErrorEvent(LifecycleEvent):            # line 15
    failed_subscriber: str; original_event_class: str  # lines 41-42
    error_type: str; error_message: str; traceback: str # lines 43-45
    def to_dict(self) -> dict[str, Any]: ...           # line 47 — traceback truncated to last 20 lines

# parrot/core/events/lifecycle/subscribers/opentelemetry.py (FEAT-176 stub — DO NOT MODIFY)
class OpenTelemetrySubscriber:                         # line 39
    def __init__(self, *, service_name="parrot", endpoint=None, tracer_provider=None): ...  # line 65
    def register(self, registry: "EventRegistry") -> None: ...   # line 100

# parrot/clients/base.py — AbstractClient
class AbstractClient:
    client_type: str = "generic"                       # line 248 (class attribute)
    client_name: str = "generic"                       # line 249 (class attribute)
    # __init__ overrides via kwargs at line 317
    def __init__(self, ...):
        self.client_type: str = kwargs.get('client_type', self.client_type)   # line 317

# parrot/models/basic.py — CompletionUsage
class CompletionUsage(BaseModel):
    estimated_cost: Optional[float] = None             # line 57

# parrot/tools/abstract.py — AbstractTool
class AbstractTool:
    async def execute(self, **kwargs):
        # line 462: pctx = kwargs.pop('_permission_context', None)
        # line 496: parent_tc = pctx.trace_context if pctx is not None else None
        # line 501: pctx.trace_context = tool_tc   (child context wired back into pctx)
        ...

# parrot/tools/toolkit.py — AbstractToolkit
class AbstractToolkit:
    async def _pre_execute(self, tool_name: str, **kwargs) -> None: ...   # line 284
    # _post_execute called at line 187 of the dispatched method wrapper
```

### Per-client `client_name` values emitted on `BeforeClientCallEvent`

Verified by greping `client_name="..."` in emission sites (not the class attribute defaults):

| Client | File | Emitted `client_name` |
|---|---|---|
| GPT/OpenAI | `parrot/clients/gpt.py:182,201,778,1120,1310,1446` | `"openai"` |
| Claude (Anthropic) | `parrot/clients/claude.py:162,179,239,470,640,697,824` | `"anthropic"` |
| Claude Agent | `parrot/clients/claude_agent.py:468,491,608,641,661` | `"claude-agent"` |
| Google | `parrot/clients/google/client.py:1860,2538,2677,2879,3106` | `"google"` |
| Gemini Live | `parrot/clients/live.py:1111,1253,1269` | `"gemini-live"` |
| Groq | `parrot/clients/groq.py:300,609,654,698,750` | `"groq"` |
| Grok (xAI) | `parrot/clients/grok.py:229,417,454,517,540` | `"grok"` |
| HuggingFace | `parrot/clients/hf.py:392,505` | `"huggingface"` |
| Gemma4 | `parrot/clients/gemma4.py:511,648` | `"gemma4"` |
| NVIDIA | `parrot/clients/nvidia.py:70-71` (class attrs only — emission TBD) | `"nvidia"` |

### Existing pyproject.toml extras (verified)

```toml
# packages/ai-parrot/pyproject.toml:458-460  (added by FEAT-176)
otel = [
    "opentelemetry-api>=1.25",
    "opentelemetry-sdk>=1.25",
]
```

This feature ADDS two new extras (do NOT replace the FEAT-176 one):

```toml
# To be added:
observability = [
    "opentelemetry-api>=1.25,<2.0",
    "opentelemetry-sdk>=1.25,<2.0",
    "opentelemetry-exporter-otlp-proto-http>=1.25,<2.0",
    "opentelemetry-exporter-otlp-proto-grpc>=1.25,<2.0",
]
observability-openlit = [
    "openlit>=1.0",
]
```

### Integration Points (verified)

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ParrotTelemetryProvider.register` | `EventRegistry.subscribe` | calls `registry.subscribe(EventClass, callback)` | `provider.py:31-33` |
| `setup_telemetry` | `get_global_registry()` | `.add_provider(ParrotTelemetryProvider())` | `provider.py:36-37`, `global_registry.py:37` |
| TASK-000 patch | `EventRegistry.emit` per-subscriber bus branch | wrap `self._event_bus.emit(...)` in `asyncio.create_task` | `registry.py:276-281` |
| `GenAIOpenTelemetrySubscriber._otel_parent_context` | `TraceContext.parent_span_id` | reads to build OTel `SpanContext` | `trace.py:42`, parallel to `subscribers/opentelemetry.py:120-142` |
| `CostCalculator` | `CompletionUsage.estimated_cost` | called from subscriber, value written to span attr / metric only — model unchanged | `models/basic.py:57` |
| `attributes.build_*` | every event class | read `event.client_name`, `event.model`, `event.duration_ms`, etc. | events as listed above |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.observability.*`~~ — no module exists yet; this feature creates it.
- ~~`setup_telemetry`, `ObservabilityConfig`, `GenAIOpenTelemetrySubscriber`, `MetricsSubscriber`, `CostCalculator`, `ParrotTelemetryProvider`~~ — none exist yet.
- ~~`event.source_name`~~ — referenced incorrectly in FEAT-176's stub at `subscribers/opentelemetry.py:237`. `BeforeClientCallEvent` has no `source_name` field; the field is `client_name`. FEAT-177's `GenAIOpenTelemetrySubscriber` MUST use `event.client_name`. This is a latent bug in the FEAT-176 stub; it surfaces only at runtime and is not in our patch scope, but we MUST NOT copy the mistake. (Optional follow-up issue.)
- ~~`opentelemetry-instrumentation-*` auto-instrumenters~~ — not used; we drive spans manually from lifecycle events.
- ~~A separate `TelemetryMixin` on `AbstractClient`~~ — the original FEAT-OBS-001 brainstorm proposed it; rejected and absorbed by FEAT-176's `EventEmitterMixin`. Do NOT add a new mixin.
- ~~Per-agent `ObservabilityConfig`~~ — out of scope in Phase 1 (D7 resolved as global-only).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Async-first: every subscriber callback is `async def`. Pure-CPU helpers may be `def`.
- Pydantic v2 for all structured config (`ObservabilityConfig`).
- All env-var lookups via `navconfig.config.get(...)`, `.getboolean(...)`, `.getfloat(...)`.
- Logger pattern: `self.logger = logging.getLogger(__name__)`; no `print`.
- Frozen dataclasses for event payloads — never mutate an event; build a child if needed.
- Lazy imports for optional deps (`openlit`, `opentelemetry.exporter.otlp.proto.grpc`).
- Module-level sentinels for idempotency (no `_initialized = True` on a `setup_telemetry` global — use a `ContextVar` or a module-private dict keyed by config hash).
- Naming: NEVER name our subscriber `OpenTelemetrySubscriber` — that slot is taken by FEAT-176's stub. Use `GenAIOpenTelemetrySubscriber`.

### Hard Performance Rules (carried from brainstorm §5.2)

These MUST appear as enforced acceptance criteria, not recommendations:

1. **`BatchSpanProcessor` only.** `SimpleSpanProcessor` is forbidden and `setup_telemetry` raises `ConfigurationError` if detected.
2. **`PeriodicExportingMetricReader` only** for metrics — same reason.
3. **OpenLIT init is boot-once** — module-level sentinel.
4. **Pricing tables loaded once** at first `CostCalculator` import — no filesystem I/O in the hot path.
5. **`ClientStreamChunkEvent` is a no-op by default** for both subscribers. Only optional span-event injection when `capture_completions=True`. Never updates metrics. Never triggers an exporter flush.
6. **No-op fast path when disabled.** With `enabled=False` no subscribers are registered; FEAT-176's empty-subscriber short-circuit keeps the emit path at ~5 ns per event.
7. **Dual-emit fire-and-forget.** Guaranteed by TASK-000.
8. **Sampling configurable** via `TraceIdRatioBased(sampling_ratio)`. Default 1.0; users > 100 req/s should lower.
9. **Cardinality whitelist** per metric. Test enforces — failure is a hard fail.

### Known Risks / Gotchas

| Risk | Probability | Severity | Mitigation |
|---|---|---|---|
| OTel SDK version skew across FEAT-176 (`otel`) and FEAT-177 (`observability`) extras | Medium | High | Single pin; `observability` extra is a superset of `otel` and tightens to `<2.0`. |
| OpenLIT auto-instrument double-counts (sibling instead of child span) | Medium | Medium | Integration test asserts one parent span per request with OpenLIT spans as children. Document the contract in README. |
| Pricing table drift / model not found | High | Low | Return `None`; WARN once per `(provider, model)`; document `PARROT_PRICING_PATH`. |
| PII leak via `capture_prompts=True` | High if misconfigured | Critical | Default `False`; README warns in red; redactor stays pluggable with no default (D3). |
| Metric cardinality explosion | Medium | High | Whitelist per metric; test enforces. |
| Slow exporter blocks request (user misconfigures `SimpleSpanProcessor`) | Low | High | `setup_telemetry` raises `ConfigurationError`. |
| Webhook subscriber from FEAT-176 user YAML used for telemetry blocks request | Medium | Medium | TASK-000 patch makes `forward_to_bus` fire-and-forget at the registry level — protects everyone, not just us. |
| `gen_ai.*` SemConv attribute names renamed by OTel | Low | Low | Centralized in `attributes.py` — single point of update. |
| Cost units (USD) confusion with non-USD pricing | Low | Low | All pricing in USD; metric attribute `currency="USD"` hard-coded; non-USD = future work. |
| FEAT-176 stub bug (`event.source_name` at `subscribers/opentelemetry.py:237`) | Latent | Low | Not in our patch scope; documented in §6 Does NOT Exist. We use `event.client_name`. |

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `opentelemetry-api` | `>=1.25,<2.0` | OTel public surface (D1 pin) |
| `opentelemetry-sdk` | `>=1.25,<2.0` | OTel implementation (D1 pin) |
| `opentelemetry-exporter-otlp-proto-http` | `>=1.25,<2.0` | HTTP/protobuf exporter |
| `opentelemetry-exporter-otlp-proto-grpc` | `>=1.25,<2.0` | gRPC exporter |
| `openlit` | `>=1.0` (optional via `observability-openlit` extra) | SDK auto-instrumentation; lazy-imported |

---

## 8. Open Questions

> Resolved items reflect brainstorm decisions and the user's explicit acceptance of brainstorm recommendations for D1–D8 on 2026-05-18. They are NOT to be re-asked.

### Resolved in brainstorm (conversation Q1–Q11, 2026-05-15)

- [x] EventBus dual-emit blocking or fire-and-forget — *Resolved in brainstorm*: **Fire-and-forget** via `asyncio.create_task` (implemented by TASK-000).
- [x] Metrics in same subscriber as traces or separate — *Resolved in brainstorm*: **Separate** `MetricsSubscriber`.
- [x] `setup_telemetry()` registers in global or explicit registry — *Resolved in brainstorm*: **`global_registry` by default**, with `registry=` param for tests.
- [x] FEAT-OBS-001 modifies FEAT-176 Module 10 or produces its own — *Resolved in brainstorm*: **Produces its own** (`GenAIOpenTelemetrySubscriber`); FEAT-176 stub untouched.
- [x] OpenLIT hard or optional dep — *Resolved in brainstorm*: **Optional**, `observability-openlit` extra, lazy import.
- [x] Capture prompts/completions by default — *Resolved in brainstorm*: **`False`** by default (PII), explicit opt-in.
- [x] Cost tables bundled or external — *Resolved in brainstorm*: **Bundled JSON + override** via `PARROT_PRICING_PATH`.
- [x] Streaming span granularity — *Resolved in brainstorm*: **One span per request**; chunks as optional span events only.
- [x] Context propagation mechanism — *Resolved in brainstorm*: **`TraceContext` in `permission_context`** (inherited from FEAT-176).
- [x] Instrument `BotManager` / `AgentRegistry` lifecycle — *Resolved in brainstorm*: **No** — out of scope; FEAT-176's `AgentInitialized/Configured/StatusChanged` cover this.
- [x] Template Method vs Decorator wiring — *Resolved in brainstorm*: **Neither needed** — subscribers don't touch class hierarchies.

### Resolved by user 2026-05-18 (brainstorm §7 D1–D8, accepted as-recommended)

- [x] **D1 — Max OTel pin** — *Resolved*: pin `opentelemetry-api/sdk >=1.25,<2.0` to insulate from breaking changes.
- [x] **D2 — OpenLIT vs OpenLLMetry default** — *Resolved*: ship OpenLIT in Phase 1 behind `enable_openlit` flag. OpenLLMetry deferred to a later minor release. Keep the flag (not architectural commitment) so swapping is ~50 LOC.
- [x] **D3 — Prompt/completion redaction** — *Resolved*: **pluggable, no default redactor**. README warns. Shipping a "this is safe" regex would give false confidence.
- [x] **D4 — Docker compose location** — *Resolved*: **bundle minimal `examples/observability/`** with one stack (OpenLIT UI). Link to other community stacks from docs.
- [x] **D5 — Pricing-table refresh policy** — *Resolved*: **(a) bundled JSON updated each minor release**, with `pricing.last_updated` field per file. Warn at boot if cached pricing > 90 days old.
- [x] **D6 — Histogram bucket boundaries** — *Resolved*: hard-coded LLM-tuned defaults `[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0, 60.0]` seconds; overridable via `ObservabilityConfig.histogram_buckets`.
- [x] **D7 — Per-agent vs global telemetry config** — *Resolved*: **Phase 1 ships global only**. Per-agent overrides deferred — would couple us to YAML changes in `BotManager`.
- [x] **D8 — `service.instance.id` strategy** — *Resolved*: `f"{socket.gethostname()}-{os.getpid()}"`; fall back to UUID4 if `gethostname()` raises.

### Unresolved (deferred to implementation — not blocking the spec)

- [ ] Exact bundled-pricing values for OpenAI / Anthropic / Google / Groq / NVIDIA models at ship time — *Owner: implementer*, sourced from each provider's pricing page; `pricing.last_updated` must reflect the source date.
- [ ] Whether to ship a starter Prometheus `prometheus.yml` alongside the OpenLIT compose stack — *Owner: implementer (Phase 6)*.
- [ ] Whether the FEAT-176 stub bug at `subscribers/opentelemetry.py:237` (`event.source_name`) warrants an opportunistic micro-PR alongside TASK-000 — *Owner: reviewer to decide before merge*.

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks in one worktree).
- **Why**: TASK-000 patches shared FEAT-176 code that every subsequent module depends on. Modules 1-8 progressively build a single coherent package and would constantly conflict if run in parallel.
- **Worktree branch**: `feat-177-otel-observability` off `dev`.
- **Cross-feature dependencies**: FEAT-176 (merged 2026-05-16) — no other gating specs.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-18 | Jesus Lara | Initial spec scaffolded from brainstorm v0.2 with two adjustments per user: (1) TASK-000 added at the front to patch `EventRegistry.emit` for fire-and-forget bus dispatch; (2) D1-D8 resolved inline using brainstorm recommendations. Codebase Contract verified against `dev` HEAD on 2026-05-18 (FEAT-176 merged 2026-05-16). |
