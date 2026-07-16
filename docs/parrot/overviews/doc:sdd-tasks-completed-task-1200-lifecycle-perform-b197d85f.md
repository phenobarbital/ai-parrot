---
type: Wiki Overview
title: 'TASK-1200: Add performance benchmarks for lifecycle events'
id: doc:sdd-tasks-completed-task-1200-lifecycle-performance-benchmarks-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Two acceptance criteria in spec §5 are performance contracts:'
relates_to:
- concept: mod:parrot.core.events.lifecycle
  rel: mentions
---

# TASK-1200: Add performance benchmarks for lifecycle events

**Feature**: FEAT-176 — Lifecycle Events System
**Spec**: `sdd/specs/FEAT-176-lifecycle-events-system.md`
**Status**: pending
**Priority**: low
**Estimated effort**: M
**Depends-on**: TASK-1186, TASK-1189
**Assigned-to**: unassigned
**Parallel**: yes (different file from TASK-1198 / TASK-1199)

---

## Context

Two acceptance criteria in spec §5 are performance contracts:

> - Performance benchmark: emitting 10,000 events with 5 subscribers each completes in < 500 ms on reference hardware (single-process, no bus, no OTel).
> - Performance benchmark: dual-emit overhead for a single event with no bus subscribers is < 10 µs (measured by pytest-benchmark).

This task adds the `pytest-benchmark` based regression tests that enforce those contracts. Future PRs that slow down the dispatch pipeline fail CI.

Spec section: §5 (acceptance), §7 (Performance regression risk in tight loops).

---

## Scope

- Add `pytest-benchmark` to the dev dependencies (under `dev` or `test` extras, NOT core).
- Write `packages/ai-parrot/tests/benchmarks/test_lifecycle_perf.py` with two benchmark tests:
  1. `test_throughput_10k_events_5_subscribers` — emits 10,000 `BeforeInvokeEvent`s with 5 trivial async subscribers; asserts wall-clock < 500 ms.
  2. `test_dual_emit_overhead_single_event` — single `BeforeInvokeEvent` emission with one no-op subscriber, no bus, no OTel; measures per-emit cost; asserts < 10 µs mean.
- Configure pytest-benchmark to skip benchmarks in normal test runs unless explicitly invoked (e.g., `pytest --benchmark-only`).
- Document the benchmark invocation in the doc added by TASK-1199 (or here in a brief `tests/benchmarks/README.md`).

**NOT in scope**: continuous benchmarking infrastructure, dashboards, alerting.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | Add `pytest-benchmark` to dev/test extras. |
| `packages/ai-parrot/tests/benchmarks/__init__.py` | CREATE | Empty package marker. |
| `packages/ai-parrot/tests/benchmarks/test_lifecycle_perf.py` | CREATE | Two benchmark tests. |
| `packages/ai-parrot/tests/benchmarks/README.md` | CREATE | One-paragraph: how to run benchmarks. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio
import pytest

from parrot.core.events.lifecycle import (
    EventRegistry, BeforeInvokeEvent, TraceContext,
)
```

### Existing pyproject.toml format

```bash
grep -nA10 'optional-dependencies\|extras_require' packages/ai-parrot/pyproject.toml
```

Add `pytest-benchmark` in whichever format the project uses for existing test deps.

### Does NOT Exist

- ~~Async benchmark fixture~~ — `pytest-benchmark` doesn't natively support coroutines. Use `benchmark(asyncio.run, coro_factory)` or wrap with `asyncio.run` inside the benchmarked function.

---

## Implementation Notes

### Bench 1 — 10k events

```python
import asyncio
import pytest

from parrot.core.events.lifecycle import (
    EventRegistry, BeforeInvokeEvent, TraceContext,
)


@pytest.mark.benchmark(group="lifecycle-throughput")
def test_throughput_10k_events_5_subscribers(benchmark):
    async def setup_and_run():
        reg = EventRegistry(forward_to_global=False)
        async def noop(e): pass
        for _ in range(5):
            reg.subscribe(BeforeInvokeEvent, noop)
        evt = BeforeInvokeEvent(trace_context=TraceContext.new_root())
        for _ in range(10_000):
            await reg.emit(evt)

    def runner():
        asyncio.run(setup_and_run())

    result = benchmark(runner)
    # pytest-benchmark reports stats; threshold check via the json output
    # Or, use benchmark.stats and fail if mean > 0.5s
    assert benchmark.stats.stats.mean < 0.5  # 500 ms
```

### Bench 2 — single-event overhead

```python
@pytest.mark.benchmark(group="lifecycle-overhead")
def test_dual_emit_overhead_single_event(benchmark):
    reg = EventRegistry(forward_to_global=False)
    async def noop(e): pass
    reg.subscribe(BeforeInvokeEvent, noop)
    evt = BeforeInvokeEvent(trace_context=TraceContext.new_root())

    def runner():
        asyncio.run(reg.emit(evt))

    benchmark(runner)
    assert benchmark.stats.stats.mean < 10e-6  # 10 µs
```

Note: the 10 µs target may need adjustment based on actual measurement on the reference hardware. The implementer may report the measured baseline and propose a realistic threshold (e.g., 25 µs) if 10 µs proves unrealistic — document in the completion note.

### Skipping benchmarks in normal runs

In `conftest.py` (or use `pytest-benchmark`'s `--benchmark-disable` flag automatically applied to non-benchmark runs):

```python
# packages/ai-parrot/tests/benchmarks/conftest.py
import pytest

def pytest_collection_modifyitems(config, items):
    if not config.getoption("--benchmark-only", default=False):
        skip = pytest.mark.skip(reason="run with --benchmark-only")
        for item in items:
            if "benchmark" in item.keywords:
                item.add_marker(skip)
```

### Key Constraints

- Benchmarks MUST NOT run in the default `pytest` invocation. Only `pytest --benchmark-only packages/ai-parrot/tests/benchmarks/` triggers them.
- Use `asyncio.run` per iteration to keep the loop creation cost consistent — or use a single-loop pattern if `pytest-benchmark` supports it via fixtures.
- Don't import `OpenTelemetrySubscriber` (we are explicitly measuring the bare cost without OTel).

---

## Acceptance Criteria

- [ ] `pytest-benchmark` added to dev/test deps.
- [ ] `pytest --benchmark-only packages/ai-parrot/tests/benchmarks/ -v` runs both benchmarks.
- [ ] `test_throughput_10k_events_5_subscribers` mean wall-clock < 500 ms (on the implementer's reference hardware).
- [ ] `test_dual_emit_overhead_single_event` mean < 10 µs (or a documented relaxed threshold if 10 µs is unrealistic).
- [ ] Regular `pytest packages/ai-parrot/tests/ -v` runs do NOT execute the benchmarks (skipped or excluded).
- [ ] `tests/benchmarks/README.md` documents how to run benchmarks.

---

## Test Specification

(The tests ARE the benchmarks.)

---

## Agent Instructions

1. Read spec §5 (performance criteria) and §7 (Performance regression risk).
2. Confirm TASK-1186, TASK-1189 are in `sdd/tasks/completed/`.
3. Add the deps, write the tests, verify they run only under `--benchmark-only`.
4. Report measured baseline numbers in the completion note (so reviewers can compare future regressions).
5. Update the per-spec index, move this file to `sdd/tasks/completed/`.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-15
**Notes**:
- Added pytest-benchmark>=4.0 to the new `dev` extras group in pyproject.toml
- Created tests/benchmarks/__init__.py, conftest.py, test_lifecycle_perf.py, README.md
- Both benchmarks PASS under --benchmark-only
- Benchmarks SKIP in normal pytest runs (verified)
- Used persistent loop (loop.run_until_complete) for per-event overhead test to avoid asyncio.run() creation overhead

**Deviations from spec**: The per-event threshold was relaxed from < 10 µs to < 50 µs. Using asyncio.run() per iteration measures ~408 µs (loop creation dominates). With a persistent loop, the actual emit cost is ~39 µs mean. The 50 µs threshold catches genuine regressions while accounting for CI hardware variance.

**Measured baselines** (Intel i7, CPython 3.11.15, no OTel, no bus):
- 10k events / 5 subscribers: ~12.5 ms (threshold 500 ms — 40x headroom)
- Per-event overhead (persistent loop): ~39 µs mean (threshold 50 µs)
