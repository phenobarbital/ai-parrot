# TASK-2471: Multi-Endpoint Exporter Factory

**Feature**: FEAT-462 — Unified Telemetry Bus
**Spec**: `sdd/specs/unified-telemetry-bus.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2470
**Assigned-to**: unassigned

---

## Context

Adds a `make_span_exporters()` factory function that returns one OTLP exporter
per `OtlpTarget`, enabling `setup_telemetry()` (TASK-2474) to attach one
`BatchSpanProcessor` per target to the shared `TracerProvider`.

The existing `make_span_exporter(config)` remains for single-target backward
compat.

Implements spec §3 Module 2.

---

## Scope

- Add `make_span_exporters(targets, protocol)` function to `exporters.py`
- Each target gets its own exporter with the target's `endpoint` and `headers`
- Share the `protocol` parameter across all targets
- Write unit tests

**NOT in scope**: Modifying `setup_telemetry()` (TASK-2474). Metric multi-target
(not needed — metrics go to a single endpoint).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/exporters.py` | MODIFY | Add `make_span_exporters()` function |
| `packages/ai-parrot/tests/unit/observability/test_exporters_multi.py` | CREATE | Unit tests (corrected path — see TASK-2470 for the same `tests/observability/` → `tests/unit/observability/` correction) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.observability.exporters import make_span_exporter, make_metric_exporter  # exporters.py
from parrot.observability.config import OtlpTarget  # config.py — added by TASK-2470
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/observability/exporters.py:20
def make_span_exporter(config: ObservabilityConfig) -> Any:
    """Create an OTLP span exporter from config."""
    # Uses lazy imports for opentelemetry-exporter-otlp-proto-http / -grpc
    # Dispatches on config.otlp_protocol ("http/protobuf" or "grpc")
    # Returns OTLPSpanExporter instance

# packages/ai-parrot/src/parrot/observability/exporters.py:63
def make_metric_exporter(config: ObservabilityConfig) -> Any:
    ...
```

### Does NOT Exist
- ~~`make_span_exporters()`~~ — plural form does not exist; must be created in this task
- ~~`CompositeSpanExporter`~~ — NOT a thing in OTel SDK; multi-target is done via multiple `BatchSpanProcessor` instances

---

## Implementation Notes

### Pattern to Follow
```python
def make_span_exporters(
    targets: list[OtlpTarget],
    protocol: str = "http/protobuf",
) -> list[Any]:
    """Create one OTLP span exporter per target.

    Args:
        targets: List of OTLP export destinations.
        protocol: Shared protocol for all targets ("http/protobuf" or "grpc").

    Returns:
        List of span exporter instances, one per target.
    """
    exporters = []
    for target in targets:
        if protocol == "grpc":
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
        else:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
        exporters.append(
            OTLPSpanExporter(
                endpoint=target.endpoint,
                headers=target.headers or None,
            )
        )
    return exporters
```

### Key Constraints
- Follow the same lazy import pattern as `make_span_exporter()`
- Protocol dispatch (http vs grpc) matches existing logic
- Each exporter gets its own endpoint + headers from the `OtlpTarget`
- Return an empty list for empty `targets`

---

## Acceptance Criteria

- [ ] `make_span_exporters([t1, t2], "http/protobuf")` returns 2 exporters
- [ ] Empty `targets` list returns empty list
- [ ] Each exporter uses its target's endpoint and headers
- [ ] All tests pass: `pytest packages/ai-parrot/tests/observability/test_exporters_multi.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/observability/exporters.py`
- [ ] Import works: `from parrot.observability.exporters import make_span_exporters`

---

## Test Specification

```python
# packages/ai-parrot/tests/observability/test_exporters_multi.py
import pytest
from unittest.mock import patch, MagicMock
from parrot.observability.config import OtlpTarget


class TestMakeSpanExporters:
    def test_multi_target(self):
        from parrot.observability.exporters import make_span_exporters
        targets = [
            OtlpTarget(name="a", endpoint="http://a:4318"),
            OtlpTarget(name="b", endpoint="http://b:4318"),
        ]
        with patch(
            "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter"
        ) as mock_cls:
            mock_cls.return_value = MagicMock()
            result = make_span_exporters(targets)
            assert len(result) == 2
            assert mock_cls.call_count == 2

    def test_empty_targets(self):
        from parrot.observability.exporters import make_span_exporters
        assert make_span_exporters([]) == []

    def test_headers_passed_through(self):
        from parrot.observability.exporters import make_span_exporters
        target = OtlpTarget(
            name="authed", endpoint="http://x:4318",
            headers={"Authorization": "Bearer tok"},
        )
        with patch(
            "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter"
        ) as mock_cls:
            mock_cls.return_value = MagicMock()
            make_span_exporters([target])
            mock_cls.assert_called_once_with(
                endpoint="http://x:4318",
                headers={"Authorization": "Bearer tok"},
            )
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/unified-telemetry-bus.spec.md` for full context
2. **Check dependencies** — verify TASK-2470 is done (OtlpTarget model exists)
3. **Verify the Codebase Contract** — confirm `make_span_exporter` is still at exporters.py:20
4. **Update status** in `sdd/tasks/index/unified-telemetry-bus.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2471-multi-endpoint-exporter-factory.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-26
**Notes**: Added `make_span_exporters(targets, protocol)` to `exporters.py`,
above `make_span_exporter()`. For `http/protobuf` targets it appends
`/v1/traces` to each target's endpoint — this mirrors
`make_span_exporter()`'s existing suffixing behavior exactly (verified with
a direct comparison test: `test_single_target_matches_make_span_exporter`),
which TASK-2474 requires for its single-target fallback to be identical to
pre-FEAT-462 behavior. gRPC targets pass the raw endpoint + tuple-form
headers, matching the existing gRPC branch. 13 new unit tests added; full
`tests/unit/observability/` suite (144 tests) passes. `ruff check` on
`exporters.py` shows the same 4 pre-existing `RUF100` violations as before
this change (unused `# noqa: PLC0415` — a repo-wide convention on lines
this task did not touch) — 0 new violations (removed the same noqa comment
from my 2 new lazy imports since it flagged as unused there too).

**Deviations from spec**: (1) Test file path corrected to
`tests/unit/observability/` (same correction as TASK-2470). (2) The
`test_headers_passed_through` test asserts the endpoint WITH the
`/v1/traces` suffix, whereas the task's illustrative test snippet asserted
the raw endpoint with no suffix. The suffix is required for correctness
(real OTLP protocol compliance) and, more concretely, for TASK-2474's own
acceptance criterion that the single-target `otlp_endpoint` fallback must
be "byte-for-byte identical" to `make_span_exporter()` — which already
appends this suffix. Not suffixing would have silently broken that
downstream guarantee.
