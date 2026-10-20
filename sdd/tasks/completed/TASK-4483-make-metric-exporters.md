# TASK-4483: `make_metric_exporters` — one OTLP metric exporter per target

**Feature**: FEAT-705 — Observability — OTLP metrics fan-out and env-level trace/metric switches
**Spec**: `sdd/specs/observability-metrics-fanout-and-env-config.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. Traces already fan out to every `OtlpTarget` through
`make_span_exporters()` (FEAT-462). Metrics only have the single-config
`make_metric_exporter(config)`. This task adds the metric twin,
`make_metric_exporters(targets, protocol)`, so TASK-4484 can attach one
`PeriodicExportingMetricReader` per target in `setup_telemetry()`.

It is a pure factory: nothing calls it yet when this task lands.

---

## Scope

- Add `make_metric_exporters(targets, protocol="http/protobuf") -> list[Any]` to
  `exporters.py`, placed after `make_span_exporter` and before `make_metric_exporter`.
- Mirror `make_span_exporters` exactly, with `trace_exporter` → `metric_exporter`
  and `/v1/traces` → `/v1/metrics`.
- Update the module docstring to mention the multi-target metric factory.
- Add `TestMakeMetricExporters` (six tests, spec §4) to `test_exporters_multi.py`.

**NOT in scope**:
- Changing `make_metric_exporter()` in any way. It stays, unchanged (spec AC9, §8 Q3).
- Touching `setup.py` — that is TASK-4484.
- Per-target protocol or interval (spec §1 Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/exporters.py` | MODIFY | Add `make_metric_exporters` |
| `packages/ai-parrot/tests/unit/observability/test_exporters_multi.py` | MODIFY | Add `TestMakeMetricExporters` |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified on `dev` @ `89a052ec0` (2026-10-19).

### Verified Imports
```python
from parrot.observability.config import ObservabilityConfig, OtlpTarget   # verified: exporters.py:17
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter  # verified: exporters.py:148-150 (lazy)
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter  # verified: exporters.py:133-135 (lazy, aliased GrpcMetricExporter)
# test file already imports (test_exporters_multi.py:9-12):
from unittest.mock import MagicMock, patch
from parrot.observability.config import ObservabilityConfig, OtlpTarget
from parrot.observability.exporters import make_span_exporter, make_span_exporters
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/observability/exporters.py
def make_span_exporters(targets: list[OtlpTarget], protocol: str = "http/protobuf") -> list[Any]  # line 20 — THE TEMPLATE (lines 20-74)
def make_span_exporter(config: ObservabilityConfig) -> Any     # line 77 (ends line 114)
def make_metric_exporter(config: ObservabilityConfig) -> Any   # line 117; grpc headers tuple at 141; http suffix at 152

# packages/ai-parrot/src/parrot/observability/config.py
class OtlpTarget(BaseModel):            # line 22
    name: str                           # line 37
    endpoint: str                       # line 38
    headers: dict[str, str] = Field(default_factory=dict)  # line 39
```

### Does NOT Exist
- ~~`exporters.make_metric_exporters`~~ — this task creates it.
- ~~`CompositeMetricExporter` / `MultiMetricExporter`~~ — not in the OTel SDK, not in parrot. Do not write one.
- ~~`OtlpTarget.protocol`~~ — protocol is a function argument shared by all targets.
- The exporter instance's endpoint is the private `_endpoint` attribute (used by `test_exporters_multi.py:76,87`); there is no public `endpoint` property.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/observability/exporters.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/observability/test_exporters_multi.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/observability/exporters.py#make_span_exporters",
    "sym:packages/ai-parrot/src/parrot/observability/exporters.py#make_metric_exporter",
    "sym:packages/ai-parrot/src/parrot/observability/config.py#OtlpTarget"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Copy `make_span_exporters` (`exporters.py:20-74`) line for line. The only
differences are the imported module (`metric_exporter` instead of
`trace_exporter`), the class alias (`GrpcMetricExporter`), the suffix
(`/v1/metrics`) and the grpc ImportError message, which reuses the wording of
`make_metric_exporter` (`exporters.py:137-140`).

### Key Constraints
- Lazy imports inside the function. The package must import without the OTel
  exporter packages installed.
- http headers: `target.headers or None` (dict). grpc headers:
  `tuple(target.headers.items()) or None`.
- Same order as *targets*; `[]` for `[]`.
- AC2 of the spec depends on the http endpoint string being byte-identical to
  `make_metric_exporter()` for the same endpoint. Use the same expression,
  `f"{target.endpoint.rstrip('/')}/v1/metrics"`.

---

## Implementation Blueprint

### Steps (in order)
1. Insert the new function between `make_span_exporter` and `make_metric_exporter` — *why*: keeps the multi-target helpers next to their single-config siblings, as the Edit Sites table fixes.
2. Add one sentence to the module docstring — *why*: the docstring lists what the module provides.
3. Append `TestMakeMetricExporters` to the test file and import the two new names — *why*: spec §4 fixes the six test names.
4. Run the Validation Commands and `ruff check` on both files.

### `packages/ai-parrot/src/parrot/observability/exporters.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def make_metric_exporter(config: ObservabilityConfig) -> Any:' exporters.py)
# BEFORE — insert above `def make_metric_exporter(config: ObservabilityConfig) -> Any:` (verified: exporters.py:117),
# leaving two blank lines on each side.
def make_metric_exporters(
    targets: list[OtlpTarget],
    protocol: str = "http/protobuf",
) -> list[Any]:
    """Return one OTLP metric exporter per *targets* entry (FEAT-705).

    Multi-endpoint counterpart to :func:`make_metric_exporter`, shaped
    exactly like :func:`make_span_exporters`. ``setup_telemetry()`` wraps
    each exporter in its own ``PeriodicExportingMetricReader`` on a single
    shared ``MeterProvider``; there is no composite metric exporter.

    Args:
        targets: List of OTLP export destinations.
        protocol: Shared transport protocol for all targets
            (``"http/protobuf"`` or ``"grpc"``).

    Returns:
        A list of exporter instances, one per target, in the same order as
        *targets*. Empty list when *targets* is empty.

    Raises:
        ImportError: When ``protocol="grpc"`` is requested but the gRPC
            exporter package is not installed.
    """
    exporters: list[Any] = []
    for target in targets:
        if protocol == "grpc":
            try:
                from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (  # noqa: PLC0415
                    OTLPMetricExporter as GrpcMetricExporter,
                )
            except ImportError as exc:
                raise ImportError(
                    "gRPC OTLP metric exporter requires the 'observability' extra with grpcio. "
                    "Install with: pip install 'ai-parrot[observability]' grpcio"
                ) from exc
            headers = tuple(target.headers.items()) or None
            exporters.append(GrpcMetricExporter(endpoint=target.endpoint, headers=headers))
            continue

        # Default: http/protobuf — same /v1/metrics suffixing as
        # make_metric_exporter() so the single implicit target in
        # setup_telemetry() is byte-for-byte the pre-FEAT-705 endpoint.
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (  # noqa: PLC0415
            OTLPMetricExporter,
        )

        endpoint = f"{target.endpoint.rstrip('/')}/v1/metrics"
        headers = target.headers or None
        exporters.append(OTLPMetricExporter(endpoint=endpoint, headers=headers))
    return exporters
```
**Why this shape**: it is the spec §3 Module 1 skeleton, which fixes the
signature and the twin-of-`make_span_exporters` behaviour. Do not refactor
`make_metric_exporter` to call this function: AC9 requires it unchanged.

Module docstring (verified: `exporters.py:5-8`): after the sentence ending
`... ``grpc`` protocols.`, add: `The plural ``make_span_exporters`` /
``make_metric_exporters`` build one exporter per ``OtlpTarget`` (FEAT-462,
FEAT-705).`

### `packages/ai-parrot/tests/unit/observability/test_exporters_multi.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^from parrot.observability.exporters import make_span_exporter, make_span_exporters$' test_exporters_multi.py)
# REPLACE the import at line 12 with:
from parrot.observability.exporters import (
    make_metric_exporter,
    make_metric_exporters,
    make_span_exporter,
    make_span_exporters,
)

# occurrences: 1 (verified: grep -c 'class TestMakeSpanExporters:' test_exporters_multi.py)
# AFTER — append at end of file, below class TestMakeSpanExporters (verified: line 15; file ends line 91)
_HTTP_METRIC = "opentelemetry.exporter.otlp.proto.http.metric_exporter.OTLPMetricExporter"
_GRPC_METRIC = "opentelemetry.exporter.otlp.proto.grpc.metric_exporter.OTLPMetricExporter"


class TestMakeMetricExporters:
    """FEAT-705 — metric twin of TestMakeSpanExporters."""

    def test_multi_target(self) -> None:
        # FILL IN: 2 targets, patch _HTTP_METRIC, assert len == 2 and call_count == 2
        ...

    def test_empty_targets(self) -> None:
        assert make_metric_exporters([]) == []

    def test_headers_passed_through(self) -> None:
        # FILL IN: one target with headers → assert_called_once_with(endpoint=".../v1/metrics", headers={...});
        #          a second call with an empty-headers target → headers=None
        ...

    def test_endpoint_suffix_matches_single_helper(self) -> None:
        # FILL IN: real exporters (no patch). config = ObservabilityConfig(otlp_endpoint="http://default:4318/");
        #          assert make_metric_exporter(config)._endpoint ==
        #          make_metric_exporters([OtlpTarget(name="default", endpoint=config.otlp_endpoint)])[0]._endpoint
        #          — bounded by spec AC2 (byte-for-byte); the trailing slash proves rstrip parity
        ...

    def test_grpc_protocol(self) -> None:
        # FILL IN: patch _GRPC_METRIC; target with headers {"k": "v"};
        #          assert_called_once_with(endpoint="http://a:4317", headers=(("k", "v"),))
        ...

    def test_multiple_targets_preserve_order(self) -> None:
        # FILL IN: 3 real exporters; assert [e._endpoint for e in result] == [a, b, c + "/v1/metrics"]
        ...
```
**Why**: `test_headers_passed_through` and `test_grpc_protocol` patch the class
at its origin module because the factory imports it inside the function
(spec §7, `test_endpoint_composition.py:19-34`). Remove the `...` bodies once filled.

### FILL IN checklist
- [ ] `TestMakeMetricExporters.test_multi_target` — mock count assertion
- [ ] `TestMakeMetricExporters.test_headers_passed_through` — dict headers and the empty → `None` case
- [ ] `TestMakeMetricExporters.test_endpoint_suffix_matches_single_helper` — bounded by AC2
- [ ] `TestMakeMetricExporters.test_grpc_protocol` — bare endpoint, tuple headers
- [ ] `TestMakeMetricExporters.test_multiple_targets_preserve_order` — order equality

---

## Acceptance Criteria

- [ ] `make_metric_exporters` exists with the exact signature above and is importable from `parrot.observability.exporters`.
- [ ] For one http target its `_endpoint` equals `make_metric_exporter()`'s for the same endpoint (spec AC2).
- [ ] grpc targets get the bare endpoint and tuple headers.
- [ ] `make_metric_exporter()` is byte-for-byte unchanged (`git diff` shows no hunk inside it) — spec AC9.
- [ ] All six `TestMakeMetricExporters` tests pass, and the existing `TestMakeSpanExporters` tests still pass.
- [ ] `ruff check` is clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/observability/test_exporters_multi.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_exporters.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_endpoint_composition.py -q`

---

## Test Specification

See the `test_exporters_multi.py` blueprint block above. The six names are
fixed by spec §4 and must not be renamed.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug observability-metrics-fanout-and-env-config --feature-id FEAT-705`).
2. **Read the spec** for full context.
3. **Check dependencies**: none.
4. **Verify the Codebase Contract** before writing code.
5. **Update status** in `sdd/tasks/index/observability-metrics-fanout-and-env-config.json` → `"in-progress"`.
6. **Implement** from the blueprint; complete every `FILL IN`.
7. **Run** the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
8. **Commit** only the two listed files.
9. **Close** with `scripts/sdd/close_task.sh TASK-4483 observability-metrics-fanout-and-env-config verified`.
10. **Fill in** the Completion Note and commit the SDD state.

---

## Completion Note

Implemented by seat gpt-5.6-terra (codex), 1 attempt, 248s. Merge-tier validation green (91 passed). Worker diff review: no defects.

**Completed by**: sdd-worker (coder gpt-5.6-terra)
**Date**: 2026-10-19
**Notes**:

**Deviations from spec**: none
