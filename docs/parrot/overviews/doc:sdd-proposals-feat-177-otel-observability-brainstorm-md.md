---
type: Wiki Overview
title: FEAT-177 — OpenTelemetry + Cost Observability for AI-Parrot
id: doc:sdd-proposals-feat-177-otel-observability-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The original FEAT-OBS-001 brainstorm proposed a full instrumentation framework.
  With FEAT-176 in flight, large parts of it become redundant:'
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.subscribers.opentelemetry
  rel: mentions
- concept: mod:parrot.observability
  rel: mentions
- concept: mod:parrot.observability.subscribers.trace
  rel: mentions
- concept: mod:parrot.version
  rel: mentions
---

# FEAT-177 — OpenTelemetry + Cost Observability for AI-Parrot

**Type**: feature (re-scope of FEAT-OBS-001 May 2026 brainstorm)
**Status**: brainstorm v0.2 — ready for codebase research
**Owner**: Jesus Lara
**Target package**: `ai-parrot` (core)
**New top-level module**: `parrot.observability`
**Hard dependency**: **FEAT-176** (Lifecycle Events System) — must ship before this feature starts implementation
**Supersedes**: `FEAT-OBS-001-otel-observability-brainstorm.md` (May 2026)
**Date**: 2026-05-15

---

## 1. Background and re-scoping rationale

### 1.1 History

| Date | Event |
|---|---|
| Oct 2025 | Initial telemetry evaluation → decision: OpenTelemetry standard + OpenLIT for SDK auto-instrumentation. |
| May 2026 | `FEAT-OBS-001` brainstorm written, proposed a `TelemetryMixin` + manual instrumentation across `AbstractClient` and `ToolManager`. Never reached `/sdd-spec`. |
| May 15 2026 | `FEAT-176` (Lifecycle Events System) spec approved. Introduces a typed event system that absorbs ~60% of what `FEAT-OBS-001` proposed. |
| May 15 2026 | This document — re-scope of the telemetry feature on top of FEAT-176. |

### 1.2 The collapse: what FEAT-176 absorbed

The original FEAT-OBS-001 brainstorm proposed a full instrumentation framework. With FEAT-176 in flight, large parts of it become redundant:

| FEAT-OBS-001 (May 2026) | Status under FEAT-176 |
|---|---|
| `TelemetryMixin` mixin on `AbstractClient` | **Replaced** by `EventEmitterMixin` |
| Manual span wrapping of `ask`/`ask_stream`/`invoke` | **Replaced** by `Before/AfterClientCallEvent` |
| Manual span wrapping of `ToolManager.execute_tool` | **Replaced** by `Before/AfterToolCallEvent` |
| Session/user/turn context propagation plumbing | **Replaced** by `TraceContext` over `permission_context` |
| `_pre_execute` / `_post_execute` hook integration | **Replaced** by unified tool events |
| Template Method vs Decorator wiring decision | **Resolved** — neither; subscribers don't touch class hierarchies |
| Streaming span granularity decision | **Resolved** — one span per request, chunks as optional span events |
| `contextvars` vs kwargs propagation decision | **Resolved** — `TraceContext` lives in `permission_context` |

### 1.3 What survives, plus what's new

The remaining feature scope is much narrower and focused on the **semantic / metric / cost layer** that FEAT-176 explicitly does NOT cover:

1. A **rich GenAI-SemConv-compliant** OpenTelemetry subscriber (FEAT-176 ships only a stub).
2. A separate **`MetricsSubscriber`** for counters and histograms (distinct from spans).
3. **Cost tracking pipeline**: pricing tables, calculator, `gen_ai.client.cost.total` metric.
4. **`setup_telemetry()`** boot helper — single entrypoint for application init.
5. **OpenLIT integration** as opt-in for SDK-level auto-instrumentation (creates child spans for raw HTTP calls).
6. **OTLP exporter helpers** with navconfig-driven configuration.
7. **Optional Docker Compose stack** for self-hosted observability backends.

---

## 2. What FEAT-176 provides that we depend on

Before implementing FEAT-177, the following components from FEAT-176 must be available and behave as expected:

| FEAT-176 deliverable | How FEAT-177 uses it |
|---|---|
| `LifecycleEvent` typed events (15 classes) | Source data — subscriber receives them, maps them to spans/metrics |
| `EventRegistry` per-agent + `global_registry` | `setup_telemetry()` registers subscribers in `global_registry` |
| `EventRegistry.emit()` with isolated subscribers (model B) | Telemetry subscriber crashes never break agent flow |
| `TraceContext` (W3C-compliant) | Used directly as OTel span context (compatibility is the design goal) |
| `EventBus` dual-emit fire-and-forget (Q9 decision) | Allows opt-in mirroring to bus without blocking |
| `OpenTelemetrySubscriber` Module 10 stub | Coexists with the rich version we build — see §4.2 |
| `EventProvider` Protocol | Used for bundling our trace + metrics + cost subscribers into a single `ParrotTelemetryProvider` |

### 2.1 Fire-and-forget dual-emit — confirmation

A behavior we agreed on in conversation that needs to be verified once FEAT-176 lands:

> `EventRegistry.emit()` MUST dispatch to local subscribers via `await` (preserves order and error isolation), but the dual-emit to `EventBus` MUST be wrapped in `asyncio.create_task(...)` so a slow or stalled Redis never adds latency to the agent's request path.

If FEAT-176's final implementation does NOT include this, FEAT-177 must patch `EventRegistry.emit` as part of its first task (added to "Codebase Research" §8).

---

## 3. Revised scope

### 3.1 In scope

- `parrot.observability` top-level module — entry point for the entire telemetry stack.
- `ObservabilityConfig` (Pydantic v2) — central configuration.
- `setup_telemetry()` — idempotent boot helper; no-op when disabled.
- `GenAIOpenTelemetrySubscriber` — rich subscriber with full GenAI SemConv attribute mapping.
- `MetricsSubscriber` — separate subscriber for OTel metrics (counters + histograms).
- `CostCalculator` + per-provider JSON pricing tables (bundled, with optional override).
- `ParrotTelemetryProvider` — `EventProvider` bundling all three subscribers.
- OpenLIT opt-in integration (deferred to a flag, not a hard dependency).
- OTLP exporter helpers (HTTP + gRPC).
- Example `docker-compose.observability.yml` stack with OpenLIT UI / Jaeger / Grafana Tempo / Prometheus.
- Example agent definitions in `examples/` showing telemetry in action.

### 3.2 Out of scope

- Anything FEAT-176 already does (event emission, mixins, lifecycle hooks, `TraceContext` propagation).
- Agent-level instrumentation beyond what FEAT-176's events expose (no separate `BotManager` spans — those come from `BeforeInvokeEvent`).
- MCP tool instrumentation (deferred — separate FEAT, would extend tool events).
- Vector store / RAG instrumentation (deferred — separate FEAT).
- Loader observability (deferred — separate FEAT).
- Interceptor-based instrumentation (out of scope until FEAT-176 Phase 2).
- Custom dashboards / Grafana JSON layouts beyond a starter example.

---

## 4. Proposed architecture

### 4.1 Module structure

```
packages/ai-parrot/src/parrot/observability/
├── __init__.py                       # Public exports
├── config.py                         # ObservabilityConfig (Pydantic v2)
├── setup.py                          # setup_telemetry() boot helper
├── attributes.py                     # GenAI SemConv attribute builders (event → attrs)
├── provider.py                       # ParrotTelemetryProvider (EventProvider bundling all subscribers)
├── subscribers/
│   ├── __init__.py
│   ├── trace.py                      # GenAIOpenTelemetrySubscriber
│   └── metrics.py                    # MetricsSubscriber
├── cost/
│   ├── __init__.py
│   ├── calculator.py                 # CostCalculator
│   └── pricing/
│       ├── openai.json
│       ├── anthropic.json
│       ├── google.json
│       ├── groq.json
│       ├── nvidia.json
│       └── README.md                 # how the pricing table format works
├── openlit_integration.py            # Lazy-imported OpenLIT init wrapper
├── exporters.py                      # OTLP exporter factory helpers
└── examples/
    ├── docker-compose.observability.yml
    ├── grafana-dashboards/
    │   └── parrot-overview.json      # starter dashboard
    └── basic_telemetry.py            # runnable example
```

### 4.2 Coexistence with FEAT-176's Module 10

FEAT-176 ships a minimal `OpenTelemetrySubscriber` in `parrot.core.events.lifecycle.subscribers.opentelemetry`. FEAT-177 ships a richer one in `parrot.observability.subscribers.trace`.

**Naming decision to avoid clash**: FEAT-177's class is named `GenAIOpenTelemetrySubscriber` (not `OpenTelemetrySubscriber`). The two classes coexist; users select via their `setup_telemetry()` or YAML config. This is intentional — the FEAT-176 version is a sane default for users who don't need full GenAI SemConv; FEAT-177's is for production-grade observability with cost tracking.

A future minor release could deprecate FEAT-176's Module 10 in favor of FEAT-177's, but that's deliberately deferred — keeps FEAT-176 self-sufficient.

### 4.3 Initialization flow

```python
# Once at application boot (e.g., in BotManager init or app startup)
from parrot.observability import setup_telemetry, ObservabilityConfig
from navconfig import config

setup_telemetry(ObservabilityConfig(
    enabled=config.getboolean("OBSERVABILITY_ENABLED", fallback=False),
    service_name=config.get("OBSERVABILITY_SERVICE_NAME", fallback="ai-parrot"),
    service_version=config.get("OBSERVABILITY_SERVICE_VERSION", fallback=None),
    otlp_endpoint=config.get("OTEL_EXPORTER_OTLP_ENDPOINT", fallback="http://localhost:4318"),
    otlp_protocol="http/protobuf",   # or "grpc"
    enable_openlit=config.getboolean("OBSERVABILITY_OPENLIT", fallback=False),
    enable_cost_tracking=config.getboolean("OBSERVABILITY_COST", fallback=True),
    sampling_ratio=config.getfloat("OBSERVABILITY_SAMPLING", fallback=1.0),
    capture_prompts=False,         # PII: default off
    capture_completions=False,     # PII: default off
    metric_export_interval_ms=60_000,
))
```

`setup_telemetry()` is idempotent. Internally it:

1. Configures `TracerProvider` with `BatchSpanProcessor` (never `Simple`) + `OTLPSpanExporter`.
2. Configures `MeterProvider` with `PeriodicExportingMetricReader` + `OTLPMetricExporter`.
3. Creates a `Resource` with `service.name`, `service.version`, `service.instance.id`, `parrot.version`.
4. Instantiates `GenAIOpenTelemetrySubscriber`, `MetricsSubscriber`, optionally `CostCalculator`.
5. Wraps them in `ParrotTelemetryProvider` and registers via `global_registry.add_provider(provider)`.
6. If `enable_openlit=True`, lazy-imports `openlit` and calls `openlit.init(otlp_endpoint=…, application_name=…)` so it auto-instruments SDK calls as child spans under our parent spans.
7. Returns a handle for shutdown (`provider.shutdown()` flushes batches).

### 4.4 Event → Span mapping

The `GenAIOpenTelemetrySubscriber` consumes 12 of FEAT-176's events. Mapping summary:

| FEAT-176 Event | OTel action | Notes |
|---|---|---|
| `BeforeInvokeEvent` | Start span `parrot.agent.invoke` | Root span; honors `event.trace_context` |
| `AfterInvokeEvent` | End span; `Status.OK`; attach final usage attrs | — |
| `InvokeFailedEvent` | End span; `Status.ERROR`; `span.record_exception` | — |
| `BeforeClientCallEvent` | Start child span `parrot.client.<provider>.<operation>` | `gen_ai.system`, `gen_ai.request.model`, etc. |
| `AfterClientCallEvent` | End span; attach `gen_ai.usage.input_tokens`, `output_tokens`, `finish_reason`, `parrot.cost.usd` | — |
| `ClientCallFailedEvent` | End span; ERROR | — |
| `ClientStreamChunkEvent` | Optional span event (only if `capture_completions=True`) | NEVER updates metrics |
| `BeforeToolCallEvent` | Start child span `parrot.tool.<name>` | `parrot.tool.name`, `parrot.tool.class` |
| `AfterToolCallEvent` | End span; OK | — |
| `ToolCallFailedEvent` | End span; ERROR | — |
| `MessageAddedEvent` | Span event on the parent invoke span | `parrot.message.role`, `parrot.message.content_length` |
| `AgentStatusChangedEvent` | Span event on whatever span is active | — |
| `AgentInitializedEvent`, `AgentConfiguredEvent`, `ToolManagerReadyEvent` | Log only (no spans — boot-time) | — |
| `SubscriberErrorEvent` | Log at WARNING; NEVER create a span | Avoid recursion |

### 4.5 Event → Metric mapping

The `MetricsSubscriber` consumes the same events but emits OTel **metrics** (not spans):

| Event | Metric | Type | Attributes |
|---|---|---|---|
| `AfterClientCallEvent` | `gen_ai.client.token.usage` | Histogram | `gen_ai.system`, `gen_ai.response.model`, `gen_ai.token.type` (input/output) |
| `AfterClientCallEvent` | `gen_ai.client.operation.duration` | Histogram | `gen_ai.system`, `gen_ai.operation.name` |
| `BeforeClientCallEvent` | `gen_ai.client.request.count` | Counter | `gen_ai.system`, `gen_ai.request.model` |
| `ClientCallFailedEvent` | `gen_ai.client.error.count` | Counter | `gen_ai.system`, `error.type` |
| `AfterClientCallEvent` | `gen_ai.client.cost.total` | Counter (UsdAmount) | `gen_ai.system`, `gen_ai.response.model` |
| `AfterToolCallEvent` | `parrot.tool.execution.duration` | Histogram | `parrot.tool.name` |
| `ToolCallFailedEvent` | `parrot.tool.failure.count` | Counter | `parrot.tool.name`, `error.type` |
| `AfterInvokeEvent` | `parrot.agent.invoke.duration` | Histogram | `parrot.agent.name`, `parrot.invoke.method` |
| `InvokeFailedEvent` | `parrot.agent.invoke.failure.count` | Counter | `parrot.agent.name`, `error.type` |

**Cardinality guard**: an explicit attribute whitelist per metric — we don't blindly export every event field. `parrot.tool.name` is bounded (typically < 100), `gen_ai.request.model` is bounded (typically < 20). High-cardinality fields like `user_id` are **never** in metric labels (they belong to spans only).

### 4.6 Cost calculator

```python
# parrot/observability/cost/calculator.py
class CostCalculator:
    """Stateless cost calculator. Pricing tables loaded once at module init.

    Per-provider JSON in pricing/<provider>.json:
      {
        "openai:gpt-4o-2024-08-06": {
          "input_per_1m_usd":  2.50,
          "output_per_1m_usd": 10.00,
          "cached_input_per_1m_usd": 1.25,
          "valid_from": "2024-08-06",
          "source": "https://openai.com/api/pricing/"
        },
        ...
      }
    """
    def cost_usd(
        self,
        *,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_input_tokens: int = 0,
    ) -> Optional[float]: ...
```

**Override path**: if `PARROT_PRICING_PATH` env var (read via navconfig) points to a directory, files there override (deep-merge) the bundled pricing. Allows updates without redeploy.

**Unknown model behavior**: returns `None` (not zero, not error). Logs a `WARN` once per `(provider, model)` pair — never spams logs.

---

## 5. Performance budget — the hard constraint

User concern: "los tiempos son críticos para respuestas de un LLM y cada segundo que incorporemos es sensación de que el agente está tardando mucho en responder."

This shapes hard rules in the design, not just recommendations.

### 5.1 Overhead estimate per full request

Single `await bot.ask(...)` with one tool call, ~10 lifecycle events emitted, 3 subscribers (trace, metrics, optional cost):

| Component | Overhead | Why |
|---|---|---|
| Event construction (frozen dataclass × 10) | ~10 μs | Cheap struct allocation |
| Local dispatch (3 subscribers × isinstance) | ~50 μs | Already short-circuits when no match |
| OTel span creation × 6 + attrs | ~100 μs | SDK call cost |
| Cost calc (1 lookup + arithmetic) | ~5 μs | Dict lookup + 2 multiplications |
| Metric updates (counter add + histogram record × ~8) | ~30 μs | Atomic ops |
| **Total in hot path** | **~200 μs** | vs LLM latency of 200ms–30s = **0.0007% to 0.1% overhead** |

### 5.2 Hard rules baked into the spec

Non-negotiable behaviors that MUST appear as acceptance criteria:

1. **`BatchSpanProcessor` only** — `SimpleSpanProcessor` causes synchronous export on every span end and is forbidden in this codebase. Enforced by a unit test that inspects the configured processor.

2. **`PeriodicExportingMetricReader` only** for metrics — same reason.

3. **OpenLIT init is boot-once** — `setup_telemetry()` calls `openlit.init()` exactly once. Idempotency must be enforced (re-init detected via a module-level sentinel).

4. **Pricing tables loaded once** at first import of `CostCalculator`. No filesystem reads in the hot path.

5. **`ClientStreamChunkEvent` updates NEITHER spans nor metrics by default** — only optional span-event injection when `capture_completions=True` is set explicitly. The chunk event itself never triggers an exporter flush.

6. **No-op fast path when disabled** — `ObservabilityConfig.enabled=False` means `setup_telemetry()` registers no subscribers; FEAT-176's empty-subscribers short-circuit makes the emit path ~5 ns per event (just the dataclass construction + a `len(self._subs) == 0` check).

7. **Dual-emit fire-and-forget** — FEAT-176 dependency; verified during research (§8).

8. **Webhook subscribers in user YAML MUST be fire-and-forget themselves** — documented in `parrot.observability` README; we cannot enforce but we strongly recommend.

9. **Sampling configurable** — `TraceIdRatioBased(ratio)` for production environments with very high request rates. Default 1.0 (full sampling); users with > 100 req/s should lower it.

10. **Cardinality guards on metric attribute sets** — only the whitelisted attributes per metric (§4.5) are exported. No dynamic keys.

---

## 6. Decisions resolved in conversation (May 15, 2026)

| # | Question | Resolution |
|---|---|---|
| 1 | EventBus dual-emit blocking or fire-and-forget? | **Fire-and-forget** — `asyncio.create_task` around `bus.emit` |
| 2 | Metrics in same subscriber as traces or separate? | **Separate** `MetricsSubscriber` (allows Prometheus-only deployments) |
| 3 | `setup_telemetry()` registers in global or explicit registry? | **`global_registry` by default**, with `registry=` param for tests |
| 4 | FEAT-OBS-001 modifies FEAT-176 Module 10 or produces its own? | **Produces its own** (`GenAIOpenTelemetrySubscriber`); FEAT-176 module untouched and coexists |
| 5 | OpenLIT hard or optional dep? | **Optional** — `extras_require['observability-openlit']`, lazy import |
| 6 | Capture prompts/completions by default? | **`False`** by default (PII); explicit opt-in via config |
| 7 | Cost tables bundled or external? | **Bundled JSON, with override path** via `PARROT_PRICING_PATH` |
| 8 | Streaming span granularity? | One span per request; chunks as optional span events only |
| 9 | Context propagation mechanism? | **`TraceContext` in `permission_context`** (inherited from FEAT-176) |
| 10 | Instrument `BotManager`/`AgentRegistry` lifecycle? | **No** — out of scope; FEAT-176's `AgentInitialized/Configured/StatusChanged` events cover this through the regular pipeline |
| 11 | Template Method vs Decorator wiring? | **Neither needed** — subscribers don't touch class hierarchies |

---

## 7. Decisions still open — for `/sdd-spec`

- [ ] **D1 — Strict version pin range for OTel.** FEAT-176 declared `opentelemetry-api>=1.25` and `opentelemetry-sdk>=1.25`. Should we also pin a maximum (e.g., `<2.0`) to insulate from breaking changes? *Recommendation: yes, pin to `<2.0`.*

- [ ] **D2 — OpenLIT vs OpenLLMetry default selection.** Both are OTel-native LLM auto-instrumenters. OpenLIT has its own UI; OpenLLMetry (by Traceloop) has broader provider coverage and is more vendor-neutral. Could support both via `enable_openlit` and `enable_openllmetry` flags. *Recommendation: ship with OpenLIT support in Phase 1, add OpenLLMetry in a Phase 2 minor release if there's demand. Keep `enable_openlit` as a flag, not an architectural commitment.*

- [ ] **D3 — Prompt/completion capture redaction.** If `capture_prompts=True`, do we ship a default redactor (regex-based for emails, phone numbers, credit cards)? Or leave the redactor pluggable with no default? *Recommendation: pluggable, no default redactor — too risky to ship a "this is safe" redactor that gives users false confidence.*

- [ ] **D4 — Docker compose stack: bundled in repo or external?** Bundling makes onboarding easy; external avoids polluting the repo. *Recommendation: bundle a minimal `examples/observability/` with one option (OpenLIT UI) and link to other community stacks from docs.*

- [ ] **D5 — Cost table refresh policy.** Pricing changes ~monthly. Do we (a) update the bundled JSON in every minor release, (b) check for a remote pricing endpoint at boot (with cache), or (c) leave it entirely to users to override? *Recommendation: (a) with a `pricing.last_updated` field in each JSON; warn at boot if cached pricing is more than 90 days old.*

- [ ] **D6 — Metric histogram bucket boundaries.** OTel defaults are linear; for LLM latencies we need exponential buckets (10ms, 50ms, 100ms, 500ms, 1s, 5s, 30s, 60s). Should be a constant or configurable? *Recommendation: hard-coded in `MetricsSubscriber` with sane LLM defaults, override via `ObservabilityConfig.histogram_buckets`.*

- [ ] **D7 — Per-agent vs global telemetry config.** Can different agents have different sampling rates / capture flags? *Recommendation: no in Phase 1 — single global config. Per-agent overrides would couple us to YAML changes in `BotManager`. Defer.*

- [ ] **D8 — Service-instance-id strategy.** `service.instance.id` should be unique per process. Use `socket.gethostname() + os.getpid()`, or a UUID? *Recommendation: hostname + pid for debuggability; UUID falls back if hostname unavailable.*

---

## 8. Codebase research tasks (the bridge to `/sdd-spec`)

Before writing the spec, Claude Code (or a human) must verify the following against the codebase as it stands **after FEAT-176 lands**. Each finding goes into the spec's Codebase Contract section.

### 8.1 FEAT-176 verification

These items must be confirmed before FEAT-177 implementation can proceed. If any are wrong, FEAT-177's first task is to patch FEAT-176.

| # | What to verify | Where | Expected |
|---|---|---|---|
| R1 | `EventBus` dual-emit is `asyncio.create_task` (fire-and-forget), not `await` | `parrot/core/events/lifecycle/registry.py` `EventRegistry.emit` | Non-blocking dispatch to bus |
| R2 | `global_registry` singleton and `scope()` context manager work as designed | `parrot/core/events/lifecycle/global_registry.py` | `get_global_registry()` returns same instance; `scope()` isolates |
| R3 | `EventProvider` Protocol matches what we'll implement | `parrot/core/events/lifecycle/provider.py` | `register(registry)` signature |
| R4 | `TraceContext` matches W3C and is read by FEAT-176 events | `parrot/core/events/lifecycle/trace.py` | Methods `new_root`, `child`, `to/from_traceparent_header` |
| R5 | All 15 concrete event classes ship and field names match assumptions | `parrot/core/events/lifecycle/events/*.py` | Fields per FEAT-176 §2 Data Models |
| R6 | `BeforeClientCallEvent` carries enough data for span attributes (model, provider, temperature, has_tools) | `client.py` event class | Confirm all needed fields present |
| R7 | `AfterClientCallEvent` carries `input_tokens`, `output_tokens`, `duration_ms`, `finish_reason` | `client.py` event class | Required for cost calc and metrics |
| R8 | FEAT-176's `OpenTelemetrySubscriber` (Module 10) lives in `parrot.core.events.lifecycle.subscribers.opentelemetry` | filesystem | No naming conflict with our `GenAIOpenTelemetrySubscriber` |
| R9 | `SubscriberErrorEvent` not received by subscribers that themselves listen to it (recursion guard) | `EventRegistry.emit` | Tested in FEAT-176 |

### 8.2 Existing AI-Parrot surfaces

| # | What to verify | Where | Why |
|---|---|---|---|
| R10 | `AbstractClient.client_name`, `client_type`, `model` are public attributes | `parrot/clients/` (path TBD) | Required for `gen_ai.system` attribute |
| R11 | `AIMessage.usage` is `CompletionUsage` with `input_tokens` / `output_tokens` populated by every client | `parrot/models/responses.py` and each client | Source of truth for tokens — should NOT need re-parsing |
| R12 | `CompletionUsage.estimated_cost` field exists | `parrot/models/basic.py` | Either we fill it from `CostCalculator` or we deprecate it |
| R13 | Provider name → `gen_ai.system` mapping (OpenAI, Anthropic, Google, Groq, NVIDIA, HuggingFace) | `parrot/clients/*.py` | Confirm names; OTel uses `openai`, `anthropic`, `vertex_ai`, etc. |
| R14 | `AbstractTool.execute()` propagates `permission_context` | `parrot/tools/abstract.py` (path TBD) | Required for `TraceContext` propagation through tool calls |
| R15 | `AbstractToolkit._pre_execute` / `_post_execute` still exist after FEAT-176 | `parrot/tools/toolkit.py` | Confirm — they're complementary, not replaced |

…(truncated)…
