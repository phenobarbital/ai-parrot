# TASK-4484: Per-target metric readers in `setup_telemetry`

**Feature**: FEAT-705 — Observability — OTLP metrics fan-out and env-level trace/metric switches
**Spec**: `sdd/specs/observability-metrics-fanout-and-env-config.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4483
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2, AC1, AC2, AC3, AC11, AC12. `setup_telemetry()` already
derives a `targets` list (explicit `otlp_targets`, or one implicit target
wrapping `otlp_endpoint`) and attaches one `BatchSpanProcessor` per target.
The metrics section ignores that list and builds a single exporter from
`otlp_endpoint`. This task makes the metrics section reuse `targets`: one
`PeriodicExportingMetricReader` per target on the shared `MeterProvider`.

Behaviour change to keep in mind (spec §2, "Routing compatibility and
migration"): a nonempty `otlp_targets` now replaces `otlp_endpoint` for
**both** signals. That is intended; TASK-4486 documents it.

---

## Scope

- Replace the single `make_metric_exporter(config)` + one reader with
  `make_metric_exporters(targets, protocol=config.otlp_protocol)` and one reader per exporter.
- Log one `logger.info` line per attached metric target, mirroring the span loop.
- Update bullet 3 of the module docstring.
- Create `test_setup_metrics_fanout.py` with the seven `TestSetupTelemetryMetricsFanOut` tests of spec §4.

**NOT in scope**:
- Changing what `enable_traces=False` / `enable_metrics=False` construct. Providers are still built; only the subscriber is skipped (spec §8 Q1). The switch test **pins** today's behaviour, it does not change it.
- `config.py` env keys (TASK-4485). This task's tests set `enable_traces` / `enable_metrics` programmatically.
- `shutdown_telemetry()`: `MeterProvider.shutdown()` already flushes every reader (AC3).
- Extending `conftest.py` to clear `MeterProvider._all_metric_readers` (spec §4 forbids it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/setup.py` | MODIFY | One metric reader per OTLP target |
| `packages/ai-parrot/tests/unit/observability/test_setup_metrics_fanout.py` | CREATE | `TestSetupTelemetryMetricsFanOut` |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified on `dev` @ `89a052ec0` (2026-10-19).

### Verified Imports
```python
from parrot.observability.exporters import make_metric_exporters        # created by TASK-4483
from parrot.observability.config import ObservabilityConfig, OtlpTarget  # verified: config.py:22,43
from parrot.observability.setup import setup_telemetry                  # verified: setup.py:63
from opentelemetry import metrics as otel_metrics                      # verified: setup.py:98
from opentelemetry import trace as otel_trace                          # verified: setup.py:99
from opentelemetry.sdk.metrics import MeterProvider                    # verified: setup.py:100
from opentelemetry.sdk.metrics.export import (                         # verified: installed opentelemetry-sdk 1.45.1
    InMemoryMetricReader, MetricExporter, MetricExportResult, PeriodicExportingMetricReader,
)
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult  # verified: installed opentelemetry-sdk 1.45.1
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/observability/setup.py
def setup_telemetry(config: ObservabilityConfig) -> Optional[ParrotTelemetryProvider]  # line 63
#   targets: list[OtlpTarget] = config.otlp_targets or [OtlpTarget(name="default", ...)]  # lines 137-143
#   span loop + logger.info("setup_telemetry: attached OTLP target '%s' -> %s", ...)     # lines 148-154
#   from parrot.observability.exporters import make_metric_exporter  # noqa: PLC0415   # line 179
#   metric_exporter = make_metric_exporter(config)                                     # line 201
#   reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=...) # lines 202-205
#   meter_provider = MeterProvider(resource=resource, metric_readers=[reader], views=views)  # lines 206-210
#   trace_sub = ... if config.enable_traces else None     # lines 240-248
#   metrics_sub = ... if config.enable_metrics else None  # lines 250-258
#   final logger.info(... otlp_targets=%d ..., len(targets))  # lines 274-281 — unchanged

# packages/ai-parrot/src/parrot/observability/provider.py
class ParrotTelemetryProvider:                       # line 26
    self._trace    # line 46 — the GenAIOpenTelemetrySubscriber or None
    self._metrics  # line 47 — the MetricsSubscriber or None

# opentelemetry-sdk 1.45.1
MeterProvider.__init__(..., metric_readers: Sequence[MetricReader] = (), ...)
MeterProvider._metric_readers     # instance attribute: this provider's own readers
MetricExporter.__init__(self, preferred_temporality=None, preferred_aggregation=None)  # abstract: export, force_flush, shutdown
TracerProvider._active_span_processor._span_processors   # used by test_setup_multi_target.py:36
```

### Does NOT Exist
- ~~`MeterProvider._sdk_config.metric_readers`~~ — not on 1.45.1.
- ~~Counting `MeterProvider._all_metric_readers`~~ — it is a **class-wide** `WeakSet` shared by every provider in the process, and shutdown does not remove entries. Never count or clear it (spec AC12).
- ~~`ParrotTelemetryProvider.trace_subscriber` / `.metrics_subscriber` attributes~~ — those are constructor kwargs; the stored attributes are `_trace` / `_metrics`.
- ~~A `CompositeMetricExporter`~~ — fan-out is N readers on one provider.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/observability/setup.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/observability/test_setup_metrics_fanout.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/observability/setup.py#setup_telemetry",
    "sym:packages/ai-parrot/src/parrot/observability/provider.py#ParrotTelemetryProvider",
    "sym:packages/ai-parrot/src/parrot/observability/config.py#OtlpTarget"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Reuse the `targets` variable computed at `setup.py:137`. Do not recompute it.
- `zip(targets, metric_exporters)` for the log lines, as the span loop does.
- Do not touch the `SimpleSpanProcessor` guard, the views, the cost calculator or the subscriber blocks.
- Tests: the package `conftest.py` resets parrot globals and the OTel `Once` latches around every test, so `otel_metrics.get_meter_provider()` returns the provider this test configured.
- Tests that need no network use fake exporters patched at their **origin module**: the factories import the class inside the function (spec §7).
- `PeriodicExportingMetricReader` reads `_preferred_temporality` / `_preferred_aggregation` from the exporter, so a `MagicMock` exporter is not safe. Subclass `MetricExporter` instead.

---

## Implementation Blueprint

### Steps (in order)
1. Change the import at `setup.py:179` — *why*: `make_metric_exporter` is no longer called by setup (it stays in `exporters.py`).
2. Replace `setup.py:201-210` with the per-target reader block — *why*: AC1/AC2.
3. Update module docstring bullet 3 (`setup.py:13-14`) — *why*: it describes a single reader.
4. Create the test file — *why*: spec §4 fixes seven test names.
5. Run the Validation Commands; the existing span tests must stay green.

### `packages/ai-parrot/src/parrot/observability/setup.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.observability.exporters import make_metric_exporter  # noqa: PLC0415' setup.py)
# REPLACE line 179 with:
        from parrot.observability.exporters import make_metric_exporters  # noqa: PLC0415

# occurrences: 1 (verified: grep -c 'metric_exporter = make_metric_exporter(config)' setup.py)
# REPLACE lines 201-210 (from `metric_exporter = make_metric_exporter(config)` through the closing `)` of
# `MeterProvider(...)`, i.e. up to but excluding `otel_metrics.set_meter_provider(meter_provider)`) with:
        # FEAT-705: one PeriodicExportingMetricReader per OTLP target, reusing
        # the same `targets` list as the span processors above, so both
        # signals reach the same destinations. An empty otlp_targets yields
        # the single implicit target — the pre-FEAT-705 single-reader path.
        metric_exporters = make_metric_exporters(targets, protocol=config.otlp_protocol)
        readers = [
            PeriodicExportingMetricReader(
                exporter,
                export_interval_millis=config.metric_export_interval_ms,
            )
            for exporter in metric_exporters
        ]
        for target in targets:
            logger.info(
                "setup_telemetry: attached OTLP metric target '%s' -> %s",
                target.name,
                target.endpoint,
            )
        meter_provider = MeterProvider(
            resource=resource,
            metric_readers=readers,
            views=views,
        )
```
Module docstring (verified: `setup.py:13`, occurrences 1): rewrite bullet 3 so
it reads `3. Configures a ``MeterProvider`` with one
``PeriodicExportingMetricReader`` per OTLP target (FEAT-705) + histogram`
and keep the rest of the bullet's existing continuation line(s).

**Why**: spec §3 Module 2 skeleton. The reader interval stays global
(`config.metric_export_interval_ms`); per-target intervals are a Non-Goal.

### `packages/ai-parrot/tests/unit/observability/test_setup_metrics_fanout.py` (CREATE)
```python
"""FEAT-705 — setup_telemetry() attaches one metric reader per OTLP target.

Global telemetry state is reset around every test by the package conftest.
Reader counts always use the configured provider's own ``_metric_readers``,
never the SDK-wide ``MeterProvider._all_metric_readers`` (spec AC12).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from opentelemetry import metrics as otel_metrics
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    InMemoryMetricReader,
    MetricExporter,
    MetricExportResult,
)
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from parrot.observability.config import ObservabilityConfig, OtlpTarget
from parrot.observability.setup import setup_telemetry

_HTTP_METRIC = "opentelemetry.exporter.otlp.proto.http.metric_exporter.OTLPMetricExporter"
_HTTP_SPAN = "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter"


class _FakeMetricExporter(MetricExporter):
    """Network-free metric exporter that records its constructor kwargs."""

    instances: list["_FakeMetricExporter"] = []

    def __init__(self, endpoint: str | None = None, headers: Any = None, **_: Any) -> None:
        super().__init__()
        self.endpoint = endpoint
        self.headers = headers
        _FakeMetricExporter.instances.append(self)

    def export(self, metrics_data: Any, timeout_millis: float = 10_000, **_: Any) -> MetricExportResult:
        return MetricExportResult.SUCCESS

    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        return True

    def shutdown(self, timeout_millis: float = 30_000, **_: Any) -> None:
        return None


class _FakeSpanExporter(SpanExporter):
    """Network-free span exporter that records its constructor kwargs."""

    instances: list["_FakeSpanExporter"] = []

    def __init__(self, endpoint: str | None = None, headers: Any = None, **_: Any) -> None:
        self.endpoint = endpoint
        self.headers = headers
        _FakeSpanExporter.instances.append(self)

    def export(self, spans: Any) -> SpanExportResult:
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None


@pytest.fixture
def fake_exporters():
    """Patch both http exporters at their origin modules; yield the two fake classes."""
    _FakeMetricExporter.instances = []
    _FakeSpanExporter.instances = []
    with patch(_HTTP_METRIC, _FakeMetricExporter), patch(_HTTP_SPAN, _FakeSpanExporter):
        yield _FakeMetricExporter, _FakeSpanExporter


def _readers(provider: Any) -> list[Any]:
    assert hasattr(provider, "_metric_readers"), (
        "MeterProvider._metric_readers is missing; this OTel version renamed it — update the test"
    )
    return list(provider._metric_readers)


def _cfg(targets: list[OtlpTarget] | None = None, **kw: Any) -> ObservabilityConfig:
    return ObservabilityConfig(enabled=True, enable_cost_tracking=False, otlp_targets=targets or [], **kw)


class TestSetupTelemetryMetricsFanOut:
    def test_two_targets_attach_two_metric_readers(self, fake_exporters) -> None:
        # FILL IN: 2 targets → len(_readers(otel_metrics.get_meter_provider())) == 2 — AC1
        ...

    def test_single_endpoint_fallback_one_reader(self, fake_exporters) -> None:
        # FILL IN: empty targets, otlp_endpoint="http://default:4318" → 1 reader whose exporter endpoint
        #          == "http://default:4318/v1/metrics" — AC2
        ...

    def test_readers_use_configured_interval(self) -> None:
        # FILL IN: patch "opentelemetry.sdk.metrics.export.PeriodicExportingMetricReader" with
        #          wraps=the real class; metric_export_interval_ms=5_000; 2 targets; assert every call
        #          has export_interval_millis=5000 — AC3. Patch at the origin module: setup.py imports it lazily.
        ...

    def test_span_and_metric_target_counts_match(self, fake_exporters) -> None:
        # FILL IN: 3 targets → 3 span processors (otel_trace.get_tracer_provider()._active_span_processor
        #          ._span_processors) and 3 metric readers
        ...

    def test_reader_count_excludes_other_providers(self, fake_exporters) -> None:
        # FILL IN: build an unrelated MeterProvider(metric_readers=[InMemoryMetricReader()]) and keep it
        #          alive; setup 2 targets; assert the configured provider has exactly 2 readers and the
        #          unrelated reader is not among them; shut the unrelated provider down in `finally`.
        #          Never touch MeterProvider._all_metric_readers — AC12
        ...

    def test_explicit_targets_override_single_endpoint_for_both_signals(self, fake_exporters) -> None:
        # FILL IN: otlp_endpoint="http://localhost:9090/api/v1/otlp" (Prometheus) and
        #          targets=[OtlpTarget(name="openlit", endpoint="http://openlit:4318")]; assert every
        #          _FakeMetricExporter and _FakeSpanExporter endpoint starts with "http://openlit:4318" and
        #          none contains "9090" — AC11
        ...

    @pytest.mark.parametrize(
        ("traces", "metrics"),
        [(False, True), (True, False), (False, False)],
        ids=["traces-off", "metrics-off", "both-off"],
    )
    def test_signal_switches_skip_subscribers_keep_providers(self, fake_exporters, traces, metrics) -> None:
        # FILL IN: provider = setup_telemetry(_cfg(enable_traces=traces, enable_metrics=metrics));
        #          assert (provider._trace is None) == (not traces) and (provider._metrics is None) == (not metrics);
        #          assert isinstance(otel_metrics.get_meter_provider(), MeterProvider) with 1 reader and the
        #          tracer provider still has 1 span processor — spec §8 Q1 (construct-but-skip-subscriber)
        ...
```
**Why this shape**: the fake exporters subclass the SDK base classes so the
real reader and batch processor accept them, and they record constructor
kwargs so AC11 can be asserted without network. Remove `...` once filled.

### FILL IN checklist
- [ ] `test_two_targets_attach_two_metric_readers` — AC1
- [ ] `test_single_endpoint_fallback_one_reader` — AC2
- [ ] `test_readers_use_configured_interval` — AC3, patch at origin with `wraps=`
- [ ] `test_span_and_metric_target_counts_match` — symmetry with spans
- [ ] `test_reader_count_excludes_other_providers` — AC12, `finally` shutdown
- [ ] `test_explicit_targets_override_single_endpoint_for_both_signals` — AC11
- [ ] `test_signal_switches_skip_subscribers_keep_providers` — §8 Q1

---

## Acceptance Criteria

- [ ] With N `otlp_targets`, the global `MeterProvider` carries exactly N readers, each with that target's endpoint/headers (spec AC1).
- [ ] With `otlp_targets=[]`, exactly one reader is built from `otlp_endpoint`, endpoint suffixed `/v1/metrics` (AC2).
- [ ] Every reader uses `config.metric_export_interval_ms` (AC3).
- [ ] Explicit targets replace the single endpoint for both signals (AC11).
- [ ] Reader-count tests use `_metric_readers` only (AC12).
- [ ] `test_setup_multi_target.py` and `test_setup.py` still pass unchanged.
- [ ] `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/observability/test_setup_metrics_fanout.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_setup_multi_target.py -q`
- `pytest packages/ai-parrot/tests/unit/observability/test_setup.py -q`
- `pytest packages/ai-parrot/tests/integration/observability/test_poc.py -q`

---

## Test Specification

See the CREATE block above; the seven test names are fixed by spec §4.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug observability-metrics-fanout-and-env-config --feature-id FEAT-705`).
2. **Check dependencies**: TASK-4483 must be `done` in the per-spec index (this task imports `make_metric_exporters`).
3. **Verify the Codebase Contract** before writing code.
4. **Update status** → `"in-progress"` in `sdd/tasks/index/observability-metrics-fanout-and-env-config.json`.
5. **Implement** from the blueprint; complete every `FILL IN`.
6. **Run** the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
7. **Commit** only the two listed files.
8. **Close** with `scripts/sdd/close_task.sh TASK-4484 observability-metrics-fanout-and-env-config verified`.
9. **Fill in** the Completion Note and commit the SDD state.

---

## Completion Note

Implemented by seat gpt-5.6-terra (codex), 1 attempt, 380s. Merge-tier validation green (100 passed). Worker diff review: no defects.

**Completed by**: sdd-worker (coder gpt-5.6-terra)
**Date**: 2026-10-19
**Notes**:

**Deviations from spec**: none
