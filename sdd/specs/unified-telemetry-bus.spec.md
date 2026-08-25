---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Unified Telemetry Bus

**Feature ID**: FEAT-462
**Date**: 2026-08-25
**Author**: Jesus Lara
**Status**: draft
**Target version**: 1.x (next minor)

---

## 1. Motivation & Business Requirements

### Problem Statement

OpenLIT 1.45 hard-caps `openai>=1.92.0,<3.0.0` while ai-parrot pins
`openai==3.3.1`. This creates an irreconcilable dependency conflict requiring
**11 `conflicting-groups` entries** in the workspace `pyproject.toml` — a
maintenance burden that grows every time a new extra touches `openai`.

The root cause: both OpenLIT and Traceloop work by **monkey-patching LLM SDK
internals**, coupling their version constraints to ours. This is architecturally
unnecessary because ai-parrot already wraps every LLM call through
`AbstractClient`, which emits rich lifecycle events (`AfterClientCallEvent`,
`BeforeClientCallEvent`, etc.) with all the telemetry data these backends need.

With OpenLIT's LLM instrumentors, metrics, and OTel provider setup all disabled
in our config, the `openlit` Python package carries a version-conflicting
dependency for effectively zero value.

**Who is affected:**
- **Operators** cannot install `ai-parrot[observability-openlit,openai]` together.
- **Developers** must maintain a growing `conflicting-groups` table.
- **CI/CD** uses a split install strategy to work around the conflict.

### Goals
- Eliminate the `openlit`/`openai` dependency conflict entirely by dropping the
  monkey-patching SDKs (`openlit`, `traceloop-sdk`)
- Support N OTLP export targets natively in `setup_telemetry()` (e.g., one for
  OpenLIT, one for Grafana Tempo) with shared protocol/sampling and per-target
  endpoint/headers
- Add an `OpenLitUsageRecorder` (`AbstractLogger` backend) that pushes
  `UsageRecord` data as GenAI SemConv OTel spans to the OpenLIT endpoint
- Fill the 2 missing GenAI SemConv attribute gaps (`gen_ai.operation.name`,
  `gen_ai.usage.cost`) for full OpenLIT dashboard compatibility
- Repurpose the `observability-openlit` / `observability-traceloop` extras to
  install a minimal bridge helper package instead of the SDK

### Non-Goals (explicitly out of scope)
- Cross-process EventBus telemetry distribution (deferred to a future FEAT —
  see brainstorm Option C/D). The `forward_to_bus=True` bridge in
  `navigator-eventbus` is the designed upgrade path.
- OpenLIT's non-LLM auto-instrumentation (DB, HTTP, etc.) — these were already
  disabled in our config and are not replaced.
- Prompt/completion content capture changes — PII guards remain as-is.

---

## 2. Architectural Design

### Overview

Replace OpenLIT/Traceloop monkey-patching SDKs with pure OTLP export from our
native lifecycle event system. The `GenAIOpenTelemetrySubscriber` already emits
GenAI SemConv-compliant spans; this feature adds the 2 missing attributes,
introduces multi-endpoint OTLP export, adds an `OpenLitUsageRecorder` for the
`AbstractLogger` fan-out layer, and removes the SDK dependencies.

OpenLIT and Traceloop become **deployment-time OTLP endpoint configurations**,
not install-time Python package dependencies.

**Config model**: A new `OtlpTarget` Pydantic model holds `name`, `endpoint`,
and optional `headers`. `ObservabilityConfig` gains an `otlp_targets: list[OtlpTarget]`
field. All targets share the global `otlp_protocol`, `sampling_ratio`, and batch
settings. The legacy `otlp_endpoint` continues to work as the single-target
default when `otlp_targets` is empty.

**Attribute compatibility**: Emit both `gen_ai.usage.cost` (OpenLIT vendor
extension) and `parrot.cost.usd` (backward compat) on every span. Add
`gen_ai.operation.name` ("chat") to `build_before_client_attrs()`.

### Component Diagram
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

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `ObservabilityConfig` | modifies | Add `OtlpTarget` model, `otlp_targets` field, deprecate `enable_openlit`/`enable_traceloop` |
| `make_span_exporter()` | modifies | Accept `OtlpTarget`, new `make_span_exporters()` for multi-target list |
| `setup_telemetry()` | modifies | Multi-BSP loop over targets, remove `init_openlit()` call |
| `ensure_observability_bootstrapped()` | modifies | Remove traceloop/openlit branching, add OpenLIT recorder path |
| `build_after_client_attrs()` | modifies | Add `gen_ai.operation.name` and `gen_ai.usage.cost` |
| `build_recorders_from_config()` | modifies | Add `"openlit"` backend branch |
| `openlit_integration.py` | **deletes** | Replaced by pure OTLP export |
| `traceloop_integration.py` | **deletes** | Replaced by pure OTLP export |
| `pyproject.toml` (workspace root) | modifies | Remove 11 `conflicting-groups` entries |
| `pyproject.toml` (ai-parrot) | modifies | Repurpose `observability-openlit`/`observability-traceloop` extras |

### Data Models
```python
class OtlpTarget(BaseModel):
    """One OTLP export destination."""
    name: str                          # human label ("openlit", "tempo")
    endpoint: str                      # OTLP base URL
    headers: dict[str, str] = Field(default_factory=dict)  # auth headers
```

### New Public Interfaces
```python
# New recorder in parrot/observability/recorders/openlit_recorder.py
class OpenLitUsageRecorder(AbstractLogger):
    """Push UsageRecords as GenAI SemConv OTel spans to an OTLP endpoint."""
    name: str = "openlit"

    def __init__(self, *, endpoint: str, headers: dict[str, str] | None = None,
                 service_name: str = "ai-parrot") -> None: ...
    async def record(self, record: UsageRecord) -> None: ...
    async def aclose(self) -> None: ...

# New multi-target exporter factory
def make_span_exporters(
    targets: list[OtlpTarget],
    protocol: str = "http/protobuf",
) -> list[Any]: ...
```

---

## 3. Module Breakdown

### Module 1: Config Model Extensions
- **Path**: `parrot/observability/config.py`
- **Responsibility**: Add `OtlpTarget` model, `otlp_targets` field,
  `openlit_recorder_endpoint` field. Deprecate `enable_openlit` and
  `enable_traceloop` (keep fields, emit `DeprecationWarning` on truthy).
  Add `OTLP_TARGETS` and `OBSERVABILITY_OPENLIT_RECORDER` env var parsing
  to `from_env()`. Deprecate `"traceloop"` as a `UsageBackend` value
  (maps to `"otel"` with a warning).
- **Depends on**: none

### Module 2: Multi-Endpoint Exporter Factory
- **Path**: `parrot/observability/exporters.py`
- **Responsibility**: New `make_span_exporters(targets, protocol)` function
  that returns a list of OTLP span exporters, one per target. The existing
  `make_span_exporter(config)` continues to work for single-target use.
  New `make_metric_exporters()` if metrics also need multi-target (optional
  — metrics typically go to a single Prometheus/OTLP endpoint).
- **Depends on**: Module 1 (`OtlpTarget`)

### Module 3: GenAI SemConv Attribute Additions
- **Path**: `parrot/observability/attributes.py`
- **Responsibility**: Add `gen_ai.operation.name` = `"chat"` to
  `build_before_client_attrs()`. Add `gen_ai.usage.cost` alongside existing
  `parrot.cost.usd` in `build_after_client_attrs()` (emit both). Update
  the `PROVIDER_TO_GEN_AI_SYSTEM` dict if needed.
- **Depends on**: none

### Module 4: OpenLIT Usage Recorder
- **Path**: `parrot/observability/recorders/openlit_recorder.py`
- **Responsibility**: `OpenLitUsageRecorder(AbstractLogger)` that creates a
  dedicated `TracerProvider` + `OTLPSpanExporter` pointed at the OpenLIT
  endpoint. On `record(UsageRecord)`, creates a span named `"parrot.usage"`
  with GenAI SemConv attributes (`gen_ai.provider.name`, `gen_ai.request.model`,
  `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`,
  `gen_ai.usage.cost`, `gen_ai.operation.name`) plus `trace_id` for
  correlation. On `aclose()`, flushes and shuts down the provider.
- **Depends on**: Module 3 (attribute naming alignment)

### Module 5: Setup Telemetry Refactor
- **Path**: `parrot/observability/setup.py`
- **Responsibility**: Refactor `setup_telemetry()` to loop over
  `config.otlp_targets` (or wrap `config.otlp_endpoint` into a single-element
  list for backward compat). Create one `BatchSpanProcessor` per target via
  `make_span_exporters()`. Remove the `init_openlit(config)` call at step 7.
- **Depends on**: Module 1, Module 2

### Module 6: Bootstrap Cleanup
- **Path**: `parrot/observability/bootstrap.py`
- **Responsibility**: Remove the `enable_traceloop` / `enable_openlit` branching
  from `_do_bootstrap()`. The `"traceloop"` backend value maps to `"otel"` with
  a deprecation log. When `OBSERVABILITY_OPENLIT_RECORDER=true`, add
  `OpenLitUsageRecorder` to the recorder list via `build_recorders_from_config()`.
  Remove the traceloop-specific flush from `shutdown_observability()`.
- **Depends on**: Module 1, Module 4

### Module 7: Delete Monkey-Patching Integrations
- **Path**: `parrot/observability/openlit_integration.py` (DELETE),
  `parrot/observability/traceloop_integration.py` (DELETE)
- **Responsibility**: Remove these files. Update `__init__.py` to remove
  `init_traceloop`, `setup_traceloop`, `shutdown_traceloop` from `__all__` and
  imports. Remove `init_openlit` from internal references.
- **Depends on**: Module 5, Module 6

### Module 8: Dependency Cleanup
- **Path**: `packages/ai-parrot/pyproject.toml`, `pyproject.toml` (workspace root)
- **Responsibility**: Change `observability-openlit` extra from
  `openlit>=1.40.0` to `ai-parrot-openlit-bridge`. Change
  `observability-traceloop` extra from `traceloop-sdk>=0.40.0,<1.0` to
  `ai-parrot-traceloop-bridge` (or remove if Traceloop bridge is deferred).
  Remove all 11 openlit-related `conflicting-groups` entries from the
  workspace root `pyproject.toml`.
- **Depends on**: Module 7

### Module 9: Bridge Package
- **Path**: `packages/ai-parrot-openlit-bridge/` (NEW package)
- **Responsibility**: Minimal package containing:
  (1) `validate_endpoint(url)` — async probe that checks OTLP endpoint
  reachability and returns collector metadata.
  (2) `parrot-openlit-check` CLI entry point.
  (3) Bundled `docker-compose.openlit.yml` snippet.
  Zero heavy dependencies — only `aiohttp` (already a workspace dep).
- **Depends on**: none (independent package)

### Module 10: Tests
- **Path**: `tests/observability/`
- **Responsibility**: Unit tests for each module. Integration test with a
  mock OTLP collector verifying spans arrive with correct attributes.
  Deprecation warning tests. Recorder fan-out test.
- **Depends on**: all modules

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_otlp_target_model` | 1 | Validates `OtlpTarget` construction and serialization |
| `test_otlp_targets_env_parsing` | 1 | `from_env()` reads `OTLP_TARGETS` JSON |
| `test_deprecated_enable_openlit_warning` | 1 | `enable_openlit=True` emits `DeprecationWarning` |
| `test_deprecated_enable_traceloop_warning` | 1 | `enable_traceloop=True` emits `DeprecationWarning` |
| `test_traceloop_backend_maps_to_otel` | 1 | `usage_backend="traceloop"` resolves to `"otel"` with warning |
| `test_make_span_exporters_multi` | 2 | Creates N exporters from N targets |
| `test_make_span_exporters_empty` | 2 | Empty list falls back to single `otlp_endpoint` |
| `test_gen_ai_operation_name_attr` | 3 | `build_before_client_attrs()` includes `gen_ai.operation.name` |
| `test_dual_cost_attrs` | 3 | `build_after_client_attrs()` emits both `gen_ai.usage.cost` and `parrot.cost.usd` |
| `test_openlit_recorder_record` | 4 | `OpenLitUsageRecorder.record()` creates span with correct attrs |
| `test_openlit_recorder_aclose` | 4 | `aclose()` flushes and shuts down the internal provider |
| `test_setup_telemetry_multi_target` | 5 | Multiple BSPs attached to TracerProvider |
| `test_setup_telemetry_no_openlit_init` | 5 | `openlit.init()` is NOT called |
| `test_bootstrap_no_traceloop_branch` | 6 | `_do_bootstrap()` does not import `traceloop.sdk` |
| `test_bootstrap_openlit_recorder` | 6 | `OBSERVABILITY_OPENLIT_RECORDER=true` adds recorder |
| `test_validate_endpoint_reachable` | 9 | Bridge probe returns metadata for live endpoint |
| `test_validate_endpoint_unreachable` | 9 | Bridge probe returns error for dead endpoint |

### Integration Tests
| Test | Description |
|---|---|
| `test_e2e_spans_to_mock_otlp` | Full pipeline: LLM call → lifecycle event → span exported to mock OTLP collector with correct GenAI SemConv attributes |
| `test_e2e_multi_target` | Spans arrive at 2 independent mock OTLP collectors |
| `test_e2e_recorder_standalone` | `OpenLitUsageRecorder` pushes usage spans without the full trace pipeline active |
| `test_backward_compat_single_endpoint` | Legacy `OTEL_EXPORTER_OTLP_ENDPOINT` config works unchanged |

### Test Data / Fixtures
```python
@pytest.fixture
def otlp_target_openlit():
    return OtlpTarget(name="openlit", endpoint="http://localhost:4318")

@pytest.fixture
def otlp_target_tempo():
    return OtlpTarget(
        name="tempo",
        endpoint="http://tempo:4318",
        headers={"Authorization": "Bearer test-token"},
    )

@pytest.fixture
def sample_usage_record():
    return UsageRecord(
        provider="openai", model="gpt-4o", input_tokens=100,
        output_tokens=50, cost_usd=0.002, duration_ms=1200.0,
        finish_reason="stop", trace_id="abc123",
    )
```

---

## 5. Acceptance Criteria

- [ ] `pip install ai-parrot[openai,observability-openlit]` succeeds without version conflict
- [ ] All 11 openlit-related `conflicting-groups` entries removed from workspace `pyproject.toml`
- [ ] `openlit` and `traceloop-sdk` are NOT in any dependency chain
- [ ] `OBSERVABILITY_ENABLED=true` + `OBSERVABILITY_BACKEND=otel` + single `OTEL_EXPORTER_OTLP_ENDPOINT` produces spans identical to pre-change behavior (backward compat)
- [ ] `OTLP_TARGETS='[{"name":"a","endpoint":"..."},{"name":"b","endpoint":"..."}]'` creates one `BatchSpanProcessor` per target on the shared `TracerProvider`
- [ ] Exported spans include `gen_ai.operation.name` = `"chat"` and both `gen_ai.usage.cost` + `parrot.cost.usd` cost attributes
- [ ] `OBSERVABILITY_OPENLIT_RECORDER=true` pushes `UsageRecord` data as OTel spans to the configured OpenLIT endpoint via the `AbstractLogger` fan-out
- [ ] `OBSERVABILITY_OPENLIT=true` emits a `DeprecationWarning` and is otherwise ignored (no `openlit.init()` call)
- [ ] `OBSERVABILITY_TRACELOOP=true` emits a `DeprecationWarning` and is otherwise ignored
- [ ] `usage_backend="traceloop"` maps to `"otel"` with a deprecation log warning
- [ ] `parrot-openlit-check <url>` CLI command validates OTLP endpoint reachability
- [ ] `openlit_integration.py` and `traceloop_integration.py` are deleted
- [ ] All unit tests pass (`pytest tests/observability/ -v`)
- [ ] No breaking changes to existing `ObservabilityConfig` fields (deprecated fields remain, just warn)

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports
```python
# These imports have been confirmed to work (2026-08-25):
from parrot.observability.config import ObservabilityConfig         # config.py:18
from parrot.observability.recorders.base import AbstractLogger      # base.py:16
from parrot.observability.recorders.models import UsageRecord       # models.py:22
from parrot.observability.recorders.factory import build_recorders_from_config  # factory.py:22
from parrot.observability.recorders.subscriber import UsageRecordingSubscriber  # subscriber.py:30
from parrot.observability.attributes import (
    resolve_gen_ai_system,
    build_before_client_attrs,
    build_after_client_attrs,
    PROVIDER_TO_GEN_AI_SYSTEM,
)                                                                    # attributes.py
from parrot.observability.exporters import make_span_exporter, make_metric_exporter  # exporters.py
from parrot.observability.setup import setup_telemetry, shutdown_telemetry  # setup.py
from parrot.observability.provider import ParrotTelemetryProvider    # provider.py:26
from parrot.core.events.lifecycle.events import AfterClientCallEvent  # events/client.py:45
from parrot.core.events.lifecycle import get_global_registry         # core/events/lifecycle
from navigator_eventbus import EventBus, Event, EventPriority        # navigator_eventbus
from navigator_eventbus.lifecycle.base import LifecycleEvent          # navigator_eventbus.lifecycle
```

### Existing Class Signatures
```python
# parrot/observability/config.py:18
class ObservabilityConfig(BaseModel):
    enabled: bool = False                                    # line 88
    otlp_endpoint: str = "http://localhost:4318"             # line 94
    otlp_protocol: Literal["http/protobuf", "grpc"]          # line 95
    otlp_headers: dict[str, str] = Field(default_factory=dict)  # line 96
    enable_openlit: bool = False                              # line 102
    enable_traceloop: bool = False                            # line 103
    openlit_disabled_instrumentors: list[str]                 # line 128
    openlit_log_level: int = logging.WARNING                  # line 149
    openlit_disable_metrics: bool = True                      # line 162
    usage_backend: UsageBackend = "none"                     # line 177
    # classmethod
    def from_env(cls) -> ObservabilityConfig:                # line 183

# parrot/observability/recorders/base.py:16
class AbstractLogger(ABC):
    name: str = "abstract"                                   # line 28
    async def record(self, record: UsageRecord) -> None:     # line 30
    async def aclose(self) -> None:                          # line 39

# parrot/observability/recorders/models.py:22
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
    timestamp: datetime                                      # line 74
    @computed_field
    def total_tokens(self) -> int:                           # property

# parrot/observability/recorders/subscriber.py:30
class UsageRecordingSubscriber:
    def __init__(self, *, recorders: list[AbstractLogger],
                 cost_calculator: Optional[CostCalculator] = None,
                 service_name: str = "ai-parrot") -> None:   # line 40
    def register(self, registry: EventRegistry) -> None:     # line 63
    async def _on_client_after(self, event: AfterClientCallEvent) -> None:  # line 76

# parrot/observability/subscribers/trace.py:59
class GenAIOpenTelemetrySubscriber:
    def __init__(self, *, service_name: str = "ai-parrot",
                 tracer_provider: Optional[Any] = None,
                 cost_calculator: Optional[CostCalculator] = None,
                 capture_completions: bool = False) -> None:  # line 78
    def register(self, registry: EventRegistry) -> None:      # line 107

# parrot/observability/subscribers/metrics.py:50
class MetricsSubscriber:
    def __init__(self, *, meter_provider: Optional[Any] = None,
                 service_name: str = "ai-parrot",
                 histogram_buckets: Optional[list[float]] = None,
                 cost_calculator: Optional[CostCalculator] = None) -> None:

# parrot/observability/provider.py:26
class ParrotTelemetryProvider:
    def __init__(self, *, trace_subscriber: Optional[GenAIOpenTelemetrySubscriber] = None,
                 metrics_subscriber: Optional[MetricsSubscriber] = None) -> None:  # line 43
    def register(self, registry: EventRegistry) -> None:     # line 52

# parrot/observability/exporters.py
def make_span_exporter(config: ObservabilityConfig) -> Any:   # line 20
def make_metric_exporter(config: ObservabilityConfig) -> Any: # line 63
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `OtlpTarget` | `ObservabilityConfig` | new field `otlp_targets` | `config.py` (to add) |
| `make_span_exporters()` | `setup_telemetry()` | called in BSP loop | `setup.py:134` |
| `OpenLitUsageRecorder` | `build_recorders_from_config()` | new `"openlit"` branch | `factory.py:22` |
| `OpenLitUsageRecorder` | `UsageRecordingSubscriber` | fan-out via `_recorders` list | `subscriber.py:114` |
| `gen_ai.operation.name` | `build_before_client_attrs()` | new attribute in returned dict | `attributes.py:143` |
| `gen_ai.usage.cost` | `build_after_client_attrs()` | alongside `parrot.cost.usd` | `attributes.py:182` |

### OpenLIT SemConv Attribute Reference
```python
# From openlit/semcov/__init__.py (installed 1.45.0) — the attributes the
# OpenLIT dashboard reads from OTLP spans. Our spans MUST include these.
"gen_ai.provider.name"            # line 175 — primary provider identifier
"gen_ai.operation.name"           # line 172 — "chat", "embed", etc.
"gen_ai.request.model"            # line 181 — model name on request
"gen_ai.response.model"           # line 236 — model name on response
"gen_ai.usage.input_tokens"       # line 515
"gen_ai.usage.output_tokens"      # line 516
"gen_ai.usage.cost"               # line 518 — OpenLIT vendor extension, USD
"gen_ai.client.token.usage"       # line 96  — metric histogram name
"gen_ai.client.operation.duration" # line 97  — metric histogram name
```

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.observability.exporters.make_span_exporters()`~~ — no multi-target factory exists yet; `make_span_exporter()` is singular
- ~~`parrot.observability.config.OtlpTarget`~~ — does not exist; must be created
- ~~`parrot.observability.config.ObservabilityConfig.otlp_targets`~~ — does not exist; must be added
- ~~`parrot.observability.recorders.openlit_recorder`~~ — module does not exist; must be created
- ~~`OpenLitUsageRecorder`~~ — class does not exist; must be created
- ~~`CompositeSpanExporter`~~ — NOT a thing in OTel SDK; multi-target is done via multiple `BatchSpanProcessor` instances on one `TracerProvider`
- ~~`gen_ai.operation.name` in attributes.py~~ — not emitted today; must be added to `build_before_client_attrs()`
- ~~`gen_ai.usage.cost` in attributes.py~~ — not emitted today; we currently emit `parrot.cost.usd` only
- ~~`ai-parrot-openlit-bridge` package~~ — does not exist under `packages/`; must be created
- ~~`OTLP_TARGETS` env var~~ — not read by `ObservabilityConfig.from_env()` today
- ~~`OBSERVABILITY_OPENLIT_RECORDER` env var~~ — not read today

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Recorder pattern**: Follow `PrometheusUsageRecorder` as the reference for
  a non-trivial `AbstractLogger` implementation (module-level guards, lazy
  imports, graceful error handling).
- **Exporter factory**: Extend `make_span_exporter()` pattern — lazy imports,
  protocol dispatch, clean error messages on missing deps.
- **Deprecation**: Use `warnings.warn(message, DeprecationWarning, stacklevel=2)`
  for deprecated env vars. Log at WARNING level for deprecated backend values.
- **Config model**: Use `Field(deprecated=True)` or a `model_validator` for
  deprecated fields. Keep the fields present (backward compat) — only the
  behavior changes.
- **PII guards**: Never include prompt/completion content in spans or usage
  records. The recorder must follow the same contract as `UsageRecord` (no
  content fields).

### Known Risks / Gotchas
- **Dual cost attribute**: Emitting both `gen_ai.usage.cost` and
  `parrot.cost.usd` means consumers see both. Document that `gen_ai.usage.cost`
  is the standard and `parrot.cost.usd` is the legacy name.
- **Recorder + trace overlap**: When the full OTel trace pipeline AND the
  OpenLIT recorder both target the same endpoint, usage data arrives through
  two paths (trace spans + usage spans). Document the config guidance: use the
  recorder for cost-only dashboards, the trace pipeline for full tracing.
- **OTLP_TARGETS JSON parsing**: The env var is a JSON list; malformed JSON
  must be caught and logged, falling back to the single-endpoint default.
- **BatchSpanProcessor per target**: Each BSP spawns a background thread. With
  many targets (>5), thread count grows. Document the recommendation to use an
  external OTel Collector for >3 targets.
- **Bridge package scope**: Keep `ai-parrot-openlit-bridge` minimal — only
  `aiohttp` as a dependency. The `validate_endpoint()` function is optional
  (best-effort at boot), never blocking.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `opentelemetry-sdk` | `>=1.25,<2.0` | TracerProvider, BatchSpanProcessor (already a dep) |
| `opentelemetry-exporter-otlp-proto-http` | `>=1.25,<2.0` | OTLP HTTP exporter (already a dep) |
| `opentelemetry-semantic-conventions` | `>=0.46b0` | GenAI SemConv attributes (already a dep) |
| `aiohttp` | `>=3.9` | Bridge package endpoint validation (already a workspace dep) |
| No new external dependencies required | | |

---

## 8. Open Questions

- [x] Should OpenLIT and Traceloop be OTLP-only or keep SDK dependencies? — *Resolved in brainstorm*: Pure OTLP only. Drop both SDKs.
- [x] Multi-endpoint: native or external collector? — *Resolved in brainstorm*: Native multi-endpoint in `setup_telemetry()`.
- [x] Extras: remove, deprecate, or repurpose? — *Resolved in brainstorm*: Repurpose to install minimal bridge helper.
- [x] EventBus scope: now or future? — *Resolved in brainstorm*: Future only. Focus on pure OTLP (Option B) for this feature.
- [x] OpenLIT recorder: OTLP wrapper or REST API? — *Resolved in brainstorm*: OTLP exporter wrapper.
- [x] Per-target config granularity? — *Resolved in brainstorm*: Shared protocol/sampling/batch, per-target URL + headers.
- [x] Bridge package deps? — *Resolved in brainstorm*: Minimal helper (endpoint validation + health check CLI).
- [x] Does the OpenLIT dashboard correctly render non-SDK GenAI SemConv spans? — *Resolved in brainstorm*: Yes, confirmed.
- [x] `gen_ai.usage.cost` vs `parrot.cost.usd`? — *Resolved in brainstorm*: Emit both for backward compatibility.
- [x] Bridge package scope? — *Resolved in brainstorm*: Three components: `validate_endpoint(url)`, `parrot-openlit-check` CLI, bundled `docker-compose.openlit.yml`.

---

## Worktree Strategy

- **Default isolation**: `per-spec` — all tasks sequential in one worktree.
- **Rationale**: While modules 1-4 and 9 are independently implementable, they
  touch a tightly coupled package (`parrot/observability/`) where changes in
  one file affect imports and behavior in others. Sequential execution avoids
  merge conflicts and ensures each task sees the previous task's changes.
  Total task count (~10) is manageable in a single worktree.
- **Cross-feature dependencies**: None. `parrot/observability/` is not actively
  modified by any in-flight feature.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-25 | Jesus Lara | Initial draft from brainstorm |
