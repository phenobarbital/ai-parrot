# TASK-2473: OpenLIT Usage Recorder

**Feature**: FEAT-462 — Unified Telemetry Bus
**Spec**: `sdd/specs/unified-telemetry-bus.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2470, TASK-2472
**Assigned-to**: unassigned

---

## Context

Creates a new `AbstractLogger` backend that pushes `UsageRecord` data as
GenAI SemConv OTel spans to an OTLP endpoint (typically OpenLIT). This
replaces the `openlit` SDK's usage tracking without requiring the SDK as a
dependency. The recorder uses its own dedicated `TracerProvider` so it can
point at a different endpoint than the main trace pipeline.

Also wires the recorder into `build_recorders_from_config()` as the
`"openlit"` backend option.

Implements spec §3 Module 4.

---

## Scope

- Create `OpenLitUsageRecorder(AbstractLogger)` class in a new module
- The recorder owns a private `TracerProvider` + `OTLPSpanExporter`
- `record(UsageRecord)` creates a span named `"parrot.usage"` with GenAI SemConv attributes
- `aclose()` flushes and shuts down the private provider
- Register `"openlit"` backend in `build_recorders_from_config()`
- Write unit tests

**NOT in scope**: Bootstrap integration (TASK-2475), multi-target setup (TASK-2474).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/recorders/openlit_recorder.py` | CREATE | OpenLitUsageRecorder implementation |
| `packages/ai-parrot/src/parrot/observability/recorders/factory.py` | MODIFY | Add `"openlit"` branch |
| `packages/ai-parrot/tests/observability/test_openlit_recorder.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.observability.recorders.base import AbstractLogger      # base.py:16
from parrot.observability.recorders.models import UsageRecord       # models.py:22
from parrot.observability.recorders.factory import build_recorders_from_config  # factory.py:22
from parrot.observability.config import ObservabilityConfig         # config.py:18
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/observability/recorders/base.py:16
class AbstractLogger(ABC):
    name: str = "abstract"                                   # line 28
    async def record(self, record: UsageRecord) -> None:     # line 30 — abstract
    async def aclose(self) -> None:                          # line 39 — abstract

# packages/ai-parrot/src/parrot/observability/recorders/models.py:22
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

# packages/ai-parrot/src/parrot/observability/recorders/factory.py:22
def build_recorders_from_config(config: ObservabilityConfig) -> list[AbstractLogger]:
    # Currently handles: "logging" → LoggingUsageRecorder,
    #                    "prometheus" → PrometheusUsageRecorder

# Reference implementation:
# packages/ai-parrot/src/parrot/observability/recorders/prometheus_recorder.py:84
class PrometheusUsageRecorder(AbstractLogger):
    name: str = "prometheus"
    # Pattern: module-level guard, lazy imports, graceful error handling
```

### Does NOT Exist
- ~~`parrot.observability.recorders.openlit_recorder`~~ — module does not exist; must be created
- ~~`OpenLitUsageRecorder`~~ — class does not exist; must be created
- ~~`CompositeSpanExporter`~~ — NOT a thing in OTel SDK

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/observability/recorders/openlit_recorder.py
"""OpenLIT usage recorder — pushes UsageRecord as OTel spans."""
import logging
from typing import Optional

from parrot.observability.recorders.base import AbstractLogger
from parrot.observability.recorders.models import UsageRecord

logger = logging.getLogger(__name__)


class OpenLitUsageRecorder(AbstractLogger):
    """Push UsageRecords as GenAI SemConv OTel spans to an OTLP endpoint.

    Uses a private TracerProvider so the recorder can target a different
    endpoint (e.g. OpenLIT) than the main trace pipeline.
    """
    name: str = "openlit"

    def __init__(
        self,
        *,
        endpoint: str,
        headers: dict[str, str] | None = None,
        service_name: str = "ai-parrot",
        protocol: str = "http/protobuf",
    ) -> None:
        # Lazy imports — module-level guard pattern from PrometheusUsageRecorder
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource

        if protocol == "grpc":
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
        else:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

        resource = Resource.create({"service.name": service_name})
        self._provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(
            endpoint=endpoint,
            headers=headers or None,
        )
        self._provider.add_span_processor(BatchSpanProcessor(exporter))
        self._tracer = self._provider.get_tracer("parrot.usage")

    async def record(self, record: UsageRecord) -> None:
        """Create a span with GenAI SemConv attributes from the UsageRecord."""
        span = self._tracer.start_span("parrot.usage")
        try:
            span.set_attribute("gen_ai.provider.name", record.provider)
            span.set_attribute("gen_ai.request.model", record.model)
            span.set_attribute("gen_ai.operation.name", "chat")
            span.set_attribute("gen_ai.usage.input_tokens", record.input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", record.output_tokens)
            if record.cost_usd is not None:
                span.set_attribute("gen_ai.usage.cost", record.cost_usd)
                span.set_attribute("parrot.cost.usd", record.cost_usd)
            if record.trace_id:
                span.set_attribute("parrot.trace_id", record.trace_id)
            span.set_attribute("service.name", record.service_name)
        finally:
            span.end()

    async def aclose(self) -> None:
        """Flush pending spans and shut down the private provider."""
        try:
            self._provider.force_flush()
            self._provider.shutdown()
        except Exception as exc:
            logger.warning("Error shutting down OpenLIT recorder: %s", exc)
```

### Key Constraints
- Follow `PrometheusUsageRecorder` patterns (module-level guard, lazy imports, graceful error handling)
- The recorder owns its OWN `TracerProvider` — do NOT use the global one
- Span name is `"parrot.usage"` (not a GenAI SemConv span name — this is usage tracking, not trace instrumentation)
- Never include prompt/completion content — only the fields from `UsageRecord`
- `aclose()` must be resilient to double-call and provider errors

### Factory Integration
```python
# In build_recorders_from_config(), add a branch:
if config.usage_backend == "openlit" or config.openlit_recorder_endpoint:
    from parrot.observability.recorders.openlit_recorder import OpenLitUsageRecorder
    recorders.append(OpenLitUsageRecorder(
        endpoint=config.openlit_recorder_endpoint or config.otlp_endpoint,
        headers=config.otlp_headers,
        service_name=config.service_name,
    ))
```

---

## Acceptance Criteria

- [ ] `OpenLitUsageRecorder(endpoint="http://...")` can be constructed
- [ ] `recorder.record(usage_record)` creates a span with correct GenAI SemConv attributes
- [ ] `recorder.aclose()` flushes and shuts down without error
- [ ] `build_recorders_from_config()` returns an `OpenLitUsageRecorder` when `usage_backend="openlit"` or `openlit_recorder_endpoint` is set
- [ ] All tests pass: `pytest packages/ai-parrot/tests/observability/test_openlit_recorder.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/observability/recorders/openlit_recorder.py`
- [ ] Import works: `from parrot.observability.recorders.openlit_recorder import OpenLitUsageRecorder`

---

## Test Specification

```python
# packages/ai-parrot/tests/observability/test_openlit_recorder.py
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone
from parrot.observability.recorders.models import UsageRecord


@pytest.fixture
def sample_record():
    return UsageRecord(
        provider="openai",
        model="gpt-4o",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.002,
        duration_ms=1200.0,
        finish_reason="stop",
        trace_id="abc123",
        service_name="ai-parrot",
        timestamp=datetime.now(timezone.utc),
    )


class TestOpenLitUsageRecorder:
    @patch("opentelemetry.sdk.trace.TracerProvider")
    @patch("opentelemetry.sdk.trace.export.BatchSpanProcessor")
    @patch("opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter")
    @patch("opentelemetry.sdk.resources.Resource")
    def test_construction(self, mock_resource, mock_exporter_cls,
                          mock_bsp, mock_provider_cls):
        from parrot.observability.recorders.openlit_recorder import OpenLitUsageRecorder
        recorder = OpenLitUsageRecorder(endpoint="http://localhost:4318")
        assert recorder.name == "openlit"

    @patch("opentelemetry.sdk.trace.TracerProvider")
    @patch("opentelemetry.sdk.trace.export.BatchSpanProcessor")
    @patch("opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter")
    @patch("opentelemetry.sdk.resources.Resource")
    async def test_record_sets_attributes(self, mock_resource, mock_exporter_cls,
                                           mock_bsp, mock_provider_cls,
                                           sample_record):
        from parrot.observability.recorders.openlit_recorder import OpenLitUsageRecorder
        recorder = OpenLitUsageRecorder(endpoint="http://localhost:4318")

        mock_span = MagicMock()
        recorder._tracer.start_span = MagicMock(return_value=mock_span)

        await recorder.record(sample_record)

        mock_span.set_attribute.assert_any_call("gen_ai.provider.name", "openai")
        mock_span.set_attribute.assert_any_call("gen_ai.request.model", "gpt-4o")
        mock_span.set_attribute.assert_any_call("gen_ai.usage.cost", 0.002)
        mock_span.end.assert_called_once()

    @patch("opentelemetry.sdk.trace.TracerProvider")
    @patch("opentelemetry.sdk.trace.export.BatchSpanProcessor")
    @patch("opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter")
    @patch("opentelemetry.sdk.resources.Resource")
    async def test_aclose_flushes(self, mock_resource, mock_exporter_cls,
                                   mock_bsp, mock_provider_cls):
        from parrot.observability.recorders.openlit_recorder import OpenLitUsageRecorder
        recorder = OpenLitUsageRecorder(endpoint="http://localhost:4318")
        await recorder.aclose()
        recorder._provider.force_flush.assert_called_once()
        recorder._provider.shutdown.assert_called_once()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/unified-telemetry-bus.spec.md` for full context
2. **Check dependencies** — verify TASK-2470 (config) and TASK-2472 (attributes) are done
3. **Verify the Codebase Contract** — read `AbstractLogger` base class and `PrometheusUsageRecorder` for the pattern
4. **Update status** in `sdd/tasks/index/unified-telemetry-bus.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2473-openlit-usage-recorder.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
