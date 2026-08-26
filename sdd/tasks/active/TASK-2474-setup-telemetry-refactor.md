# TASK-2474: Setup Telemetry Refactor

**Feature**: FEAT-462 — Unified Telemetry Bus
**Spec**: `sdd/specs/unified-telemetry-bus.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2470, TASK-2471
**Assigned-to**: unassigned

---

## Context

Refactors `setup_telemetry()` to use multi-endpoint OTLP export. Instead of
creating a single `BatchSpanProcessor`, it now loops over `config.otlp_targets`
(or wraps `config.otlp_endpoint` into a single-element list for backward compat)
and creates one BSP per target via `make_span_exporters()`. Also removes the
`init_openlit(config)` call at step 7.

Implements spec §3 Module 5.

---

## Scope

- Refactor `setup_telemetry()` to loop over `config.otlp_targets` and create one `BatchSpanProcessor` per target
- When `otlp_targets` is empty, fall back to wrapping `config.otlp_endpoint` into a single `OtlpTarget`
- Remove the `init_openlit(config)` call (currently step 7 in the function)
- Write unit tests

**NOT in scope**: Bootstrap changes (TASK-2475), file deletion (TASK-2476), dependency cleanup (TASK-2476).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/setup.py` | MODIFY | Multi-BSP loop, remove `init_openlit` call |
| `packages/ai-parrot/tests/observability/test_setup_multi_target.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.observability.setup import setup_telemetry, shutdown_telemetry  # setup.py
from parrot.observability.config import ObservabilityConfig, OtlpTarget    # config.py (OtlpTarget added by TASK-2470)
from parrot.observability.exporters import make_span_exporter, make_span_exporters  # exporters.py (make_span_exporters added by TASK-2471)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/observability/setup.py:64
def setup_telemetry(
    config: ObservabilityConfig | None = None,
    *,
    service_name: str = "ai-parrot",
    ...
) -> ...:
    # Current flow:
    # 1. Build Resource
    # 2. Create TracerProvider with single BatchSpanProcessor
    # 3. Create MeterProvider
    # 4. Create CostCalculator
    # 5. Create subscribers (trace, metrics)
    # 6. Register with EventRegistry
    # 7. Call init_openlit(config) ← THIS GETS REMOVED

# packages/ai-parrot/src/parrot/observability/exporters.py:20
def make_span_exporter(config: ObservabilityConfig) -> Any:
    # Existing single-target factory

# make_span_exporters() — added by TASK-2471
def make_span_exporters(targets: list[OtlpTarget], protocol: str = "http/protobuf") -> list[Any]:
    # Multi-target factory
```

### Does NOT Exist
- The multi-BSP loop in `setup_telemetry()` — must be implemented
- ~~`init_openlit` import in setup.py~~ — exists today but must be removed

---

## Implementation Notes

### Pattern to Follow
```python
# In setup_telemetry(), replace the single BSP creation with:

# Resolve targets: multi-target or single-target fallback
targets = config.otlp_targets
if not targets:
    targets = [OtlpTarget(
        name="default",
        endpoint=config.otlp_endpoint,
        headers=config.otlp_headers,
    )]

# Create one BatchSpanProcessor per target
from opentelemetry.sdk.trace.export import BatchSpanProcessor
exporters = make_span_exporters(targets, protocol=config.otlp_protocol)
for exporter in exporters:
    tracer_provider.add_span_processor(BatchSpanProcessor(exporter))

# REMOVE: init_openlit(config) call
```

### Key Constraints
- `TracerProvider` supports multiple `BatchSpanProcessor` instances — this is the
  designed multi-target approach in OTel SDK
- The single-target fallback must produce IDENTICAL behavior to pre-change code
- Remove the `init_openlit(config)` call AND its import (if local)
- Do NOT remove `openlit_integration.py` itself — that's TASK-2476
- Log each target name at INFO level when adding its BSP

---

## Acceptance Criteria

- [ ] `setup_telemetry(config_with_2_targets)` attaches 2 `BatchSpanProcessor` instances to the `TracerProvider`
- [ ] `setup_telemetry(config_with_no_targets)` falls back to `otlp_endpoint` — identical to pre-change behavior
- [ ] `init_openlit(config)` is NOT called anywhere in `setup_telemetry()`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/observability/test_setup_multi_target.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/observability/setup.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/observability/test_setup_multi_target.py
import pytest
from unittest.mock import patch, MagicMock, call
from parrot.observability.config import ObservabilityConfig, OtlpTarget


class TestSetupTelemetryMultiTarget:
    @patch("parrot.observability.setup.make_span_exporters")
    @patch("parrot.observability.setup.BatchSpanProcessor")
    def test_multi_target_creates_multiple_bsps(self, mock_bsp, mock_exporters):
        from parrot.observability.setup import setup_telemetry
        mock_exporters.return_value = [MagicMock(), MagicMock()]
        config = ObservabilityConfig(
            enabled=True,
            otlp_targets=[
                OtlpTarget(name="a", endpoint="http://a:4318"),
                OtlpTarget(name="b", endpoint="http://b:4318"),
            ],
        )
        # setup_telemetry should create 2 BSPs
        # (test may need adjustment based on actual function flow)

    def test_single_endpoint_fallback(self):
        """When otlp_targets is empty, falls back to otlp_endpoint."""
        config = ObservabilityConfig(
            enabled=True,
            otlp_endpoint="http://default:4318",
        )
        # Verify single-target fallback produces same behavior

    @patch("parrot.observability.setup.init_openlit", create=True)
    def test_no_openlit_init(self, mock_init):
        """setup_telemetry no longer calls init_openlit."""
        # After implementation, init_openlit should not be imported or called
        # This test verifies the removal
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/unified-telemetry-bus.spec.md` for full context
2. **Check dependencies** — verify TASK-2470 (config), TASK-2471 (exporters) are done
3. **Verify the Codebase Contract** — read `setup.py` to understand the current flow and find the `init_openlit` call
4. **Update status** in `sdd/tasks/index/unified-telemetry-bus.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2474-setup-telemetry-refactor.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
