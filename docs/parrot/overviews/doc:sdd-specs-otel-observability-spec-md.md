---
type: Wiki Overview
title: 'Feature Specification: OpenTelemetry + Cost Observability'
id: doc:sdd-specs-otel-observability-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'AI-Parrot agents make LLM calls and tool executions that are currently observable
  only through ad-hoc logging. There is no standardized way to:'
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.base
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.events
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.global_registry
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.meta
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.provider
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.registry
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.subscribers.opentelemetry
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.trace
  rel: mentions
- concept: mod:parrot.models.basic
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
- concept: mod:parrot.observability
  rel: mentions
- concept: mod:parrot.observability.config
  rel: mentions
- concept: mod:parrot.observability.cost.calculator
  rel: mentions
- concept: mod:parrot.observability.provider
  rel: mentions
- concept: mod:parrot.observability.setup
  rel: mentions
- concept: mod:parrot.observability.subscribers.metrics
  rel: mentions
- concept: mod:parrot.observability.subscribers.trace
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot.version
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: OpenTelemetry + Cost Observability

**Feature ID**: FEAT-177
**Date**: 2026-05-18
**Author**: Jesus Lara
**Status**: approved
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

…(truncated)…
