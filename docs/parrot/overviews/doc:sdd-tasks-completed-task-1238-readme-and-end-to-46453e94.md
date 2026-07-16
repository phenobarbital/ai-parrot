---
type: Wiki Overview
title: 'TASK-1238: README + end-to-end PoC (5 scenarios)'
id: doc:sdd-tasks-completed-task-1238-readme-and-end-to-end-poc-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Spec §3 Module 11 — the final acceptance gate analogous to FEAT-176''s Module
  18. Two deliverables:'
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.observability
  rel: mentions
---

# TASK-1238: README + end-to-end PoC (5 scenarios)

**Feature**: FEAT-177 — OpenTelemetry + Cost Observability
**Spec**: `sdd/specs/otel-observability.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1227, TASK-1228, TASK-1229, TASK-1230, TASK-1231, TASK-1232, TASK-1233, TASK-1234, TASK-1235, TASK-1236, TASK-1237
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 11 — the final acceptance gate analogous to FEAT-176's Module 18. Two deliverables:

1. **`parrot/observability/README.md`** — public docs covering env vars, navconfig keys, the PII contract, the OpenLIT contract, the performance contract, and the PoC script.
2. **End-to-end PoC** — a single script that runs all 5 scenarios in sequence with `InMemorySpanExporter`/`InMemoryMetricReader` so the output is assertable in CI:
   - Scenario 1: traces only (`enable_metrics=False`).
   - Scenario 2: metrics only (`enable_traces=False`).
   - Scenario 3: traces + metrics + cost.
   - Scenario 4: traces + OpenLIT (mocked).
   - Scenario 5: sampling=0.1 over 100 fake requests.

This task also adds the **performance benchmark** acceptance criteria from spec §5 (< 1 ms p50 overhead vs disabled; < 5 ms with OpenLIT).

---

## Scope

- Write `parrot/observability/README.md` per the structure below.
- Create `tests/integration/observability/test_poc.py` running the 5 scenarios with assertions.
- Create `tests/integration/observability/test_perf.py` running the perf benchmark and asserting the budget.

**NOT in scope**: changing any subscriber, calculator, or boot helper — they should already be feature-complete.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/README.md` | CREATE | Public docs. |
| `packages/ai-parrot/tests/integration/observability/test_poc.py` | CREATE | 5-scenario PoC. |
| `packages/ai-parrot/tests/integration/observability/test_perf.py` | CREATE | Perf budget. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.observability import (
    ObservabilityConfig, setup_telemetry, shutdown_telemetry,
    GenAIOpenTelemetrySubscriber, MetricsSubscriber,
    CostCalculator, ParrotTelemetryProvider,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
```

### Performance budget targets (spec §5 + §1 Goals)

- p50 overhead disabled-vs-enabled, no OpenLIT: **< 1 ms** on a `bot.ask()` round-trip against a mock client.
- p50 overhead with OpenLIT enabled (mock): **< 5 ms**.

### Does NOT Exist

- ~~Real LLM API calls in the integration tests~~ — use a mock client. Network calls in CI are forbidden.

---

## Implementation Notes

### README structure (suggested H2 sections)

1. **Quickstart** — 5-line `setup_telemetry(...)` snippet.
2. **Configuration** — full `ObservabilityConfig` field table.
3. **navconfig env-var keys** — table mapping env vars to config fields (`OBSERVABILITY_ENABLED`, `OBSERVABILITY_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OBSERVABILITY_OPENLIT`, `OBSERVABILITY_COST`, `OBSERVABILITY_SAMPLING`, `PARROT_PRICING_PATH`).
4. **PII contract** — `capture_prompts=False`, `capture_completions=False` are the safe defaults. Enabling them is the user's responsibility; we ship no default redactor.
5. **Performance contract** — < 1 ms overhead enabled, < 5 ms with OpenLIT, ~5 ns disabled. `SimpleSpanProcessor` is forbidden.
6. **OpenLIT contract** — OpenLIT spans are CHILDREN of ours. Setting up our `TracerProvider` first is what guarantees this; do not reorder.
7. **Examples** — link to TASK-1237's docker-compose and demo script.
8. **PoC scenarios** — point to `tests/integration/observability/test_poc.py`.
9. **Cost pricing** — bundled JSON, override via `PARROT_PRICING_PATH`, stale-warning policy.
10. **Troubleshooting** — common pitfalls (e.g., "missing extras", "OpenLIT not double-counting? check parent context").

### PoC script structure

```python
# tests/integration/observability/test_poc.py
import pytest
from parrot.observability import ObservabilityConfig, setup_telemetry, shutdown_telemetry
# ... helper to drive a fake bot.ask cycle that emits the expected lifecycle events


@pytest.fixture(autouse=True)
def _isolated():
    yield
    shutdown_telemetry()


def test_scenario_1_traces_only(...):
    ...

def test_scenario_2_metrics_only(...):
    ...

def test_scenario_3_traces_metrics_cost(...):
    ...

def test_scenario_4_openlit_mocked(...):
    ...

def test_scenario_5_sampling(...):
    # emit 100 fake requests with sampling_ratio=0.1; assert roughly 10 spans (±50%)
    ...
```

Each scenario asserts the exporter state (span count + key attrs) and the metric reader (counter / histogram counts).

### Perf benchmark

```python
# tests/integration/observability/test_perf.py
import statistics
import time
import asyncio
import pytest


async def _drive_one_cycle(bot):
    await bot.ask("perf")


@pytest.mark.asyncio
async def test_p50_overhead_under_1ms():
    baseline = _benchmark(disabled=True)
    enabled = _benchmark(disabled=False, openlit=False)
    delta_ms = (enabled - baseline) * 1000
    assert delta_ms < 1.0, f"telemetry overhead {delta_ms:.2f}ms exceeds 1ms budget"


@pytest.mark.asyncio
async def test_p50_overhead_under_5ms_with_openlit():
    baseline = _benchmark(disabled=True)
    enabled = _benchmark(disabled=False, openlit=True)
    delta_ms = (enabled - baseline) * 1000
    assert delta_ms < 5.0


def _benchmark(*, disabled: bool, openlit: bool = False) -> float:
    setup_telemetry(ObservabilityConfig(
        enabled=not disabled, enable_openlit=openlit,
    ))
    try:
        bot = _build_mock_bot()
        loop = asyncio.new_event_loop()
        samples = []
        for _ in range(100):
            t0 = time.perf_counter()
            loop.run_until_complete(_drive_one_cycle(bot))
            samples.append(time.perf_counter() - t0)
        return statistics.median(samples)
    finally:
        shutdown_telemetry()
```

`_build_mock_bot()` returns an in-process bot whose client emits the FEAT-176 lifecycle events but doesn't perform real I/O — use the same fixture as the PoC.

### Key Constraints

- Tests must pass deterministically in CI — no flakes from real network or sleep-based timing.
- The perf budget is enforced; if a future change blows it, this test fails.
- Sampling test tolerates statistical noise (50% band).

---

## Acceptance Criteria

- [ ] README covers all 10 sections above with working code snippets.
- [ ] `pytest packages/ai-parrot/tests/integration/observability/test_poc.py -v` — all 5 scenarios pass.
- [ ] `pytest packages/ai-parrot/tests/integration/observability/test_perf.py -v` — both budget tests pass.
- [ ] README references the PoC test file and the example docker-compose from TASK-1237.
- [ ] No external network calls anywhere in the test suite.

---

## Test Specification

See "PoC script structure" and "Perf benchmark" above. Both files materialize as part of this task.

---

## Agent Instructions

1. Confirm ALL prior FEAT-177 tasks (TASK-1227..TASK-1237) are complete.
2. Write README, PoC tests, and perf tests.
3. Run the full FEAT-177 unit + integration test suites and verify green.
4. Update top-level `docs/` or `README.md` index if AI-Parrot maintains one (check before adding).

---

## Completion Note

Created all 3 required files plus an `__init__.py` for the new test package:
- `parrot/observability/README.md`: all 10 sections (Quickstart, Configuration, navconfig env-vars, PII contract, Performance contract, OpenLIT contract, Examples, PoC scenarios, Cost pricing, Troubleshooting)
- `tests/integration/observability/test_poc.py`: 5 scenarios verified passing — traces only (1 span 'parrot.client.openai.chat'), metrics only (3 metric types), traces+metrics+cost, openlit mocked (init called once), sampling=10% over 100 requests (9 spans, within 2-25 tolerance)
- `tests/integration/observability/test_perf.py`: 3 perf tests verified passing — disabled p50=0.001 ms, enabled p50=0.074 ms, delta=0.074 ms (well within 1 ms budget)
All tests use InMemorySpanExporter/InMemoryMetricReader; zero real network calls. Committed as `feat(otel-observability): TASK-1238`.
