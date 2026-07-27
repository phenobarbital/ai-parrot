# TASK-1950: Latency budget router + circuit breaker

**Feature**: FEAT-380 — Tool Result Compression Pipeline
**Spec**: `sdd/specs/tool-result-compression.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1947
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. Compression is only worth doing if it never stalls the event
loop (G9) and never costs more than it saves (G7). This module decides, **from
a size estimate taken BEFORE compressing**, one of three routes:

| Condition | Route | Budget |
|---|---|---|
| level `MINIMAL`, any size | inline | ≤ 0.3 ms p99 |
| `NORMAL`/`AGGRESSIVE`, under threshold | inline | ≤ 1 ms p99 |
| over threshold, Rust extension present | `run_in_executor` + `allow_threads()` | ≤ 15 ms p99, off-loop |
| over threshold, **no** Rust extension | **passthrough, 0 ms** | G9 |

The last row is the one people get wrong: without `py.allow_threads()` the GIL
is still held, so `run_in_executor` buys no real parallelism — it is theater.
Sending a fat payload beats stalling the loop.

A codec that sustainedly busts its budget self-degrades to passthrough
(circuit breaker) and logs it.

---

## Scope

- Implement `budget.py` with:
  - `Route` enum: `INLINE`, `EXECUTOR`, `PASSTHROUGH`.
  - `estimate_size(payload) -> tuple[int, int]` — cheap `(bytes, rows)`
    estimate that must NOT fully serialize a large payload (see Notes).
  - `BudgetRouter.route(payload, *, level, codec_name, rust_available) -> Route`
    implementing the table above.
  - `CircuitBreaker` — per-codec rolling window of 100 calls **or** 60 s
    (whichever comes first); 3 consecutive over-budget windows → degrade that
    codec to `PASSTHROUGH` + `logger.warning`; half-open re-arm after a
    5-minute cooldown (one probe call allowed; success re-arms, failure
    restarts the cooldown).
  - `record(codec_name, duration_ms, route)` — feeds the breaker and exposes
    rolling p99 for TASK-1957's report.
- All thresholds configurable via constructor kwargs with the spec defaults:
  `size_threshold_bytes = 256 * 1024`, `row_threshold = 5000`,
  `window_calls = 100`, `window_seconds = 60`, `consecutive_windows = 3`,
  `cooldown_seconds = 300`, `inline_budget_ms = 1.0`,
  `minimal_budget_ms = 0.3`, `executor_budget_ms = 15.0`.
- Rust availability detection via `lazy_import` (`parrot/_imports.py:84`) —
  detected once, cached; absence logged once at `debug`, never per call.

**NOT in scope**:
- Actually calling the codec / running the executor → TASK-1951 (the stage
  consumes this router's decision).
- The Rust extension itself → TASK-1955. This task only *detects* it and must
  work correctly with it absent (the normal case until 1955 lands).
- Benchmark calibration of the defaults → TASK-1959.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/compression/budget.py` | CREATE | `Route`, `estimate_size`, `BudgetRouter`, `CircuitBreaker` |
| `packages/ai-parrot/src/parrot/tools/compression/__init__.py` | MODIFY | Export `Route`, `BudgetRouter` |
| `packages/ai-parrot/tests/tools/compression/test_budget.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against HEAD `024c21d44` on 2026-07-27.
> **Path mapping**: `parrot/...` means `packages/ai-parrot/src/parrot/...`.

### Verified Imports

```python
import asyncio
import time
from parrot._imports import lazy_import          # verified: parrot/_imports.py:84

# Created by TASK-1947:
from parrot.tools.compression import FilterLevel
```

### Existing Signatures to Use

```python
# parrot/_imports.py:84 — the optional-extension detection pattern
def lazy_import(module_path: str, package_name: str | None = None,
                extra: str | None = None) -> ModuleType: ...

# parrot/tools/pythonrepl.py:950 — the executor-offload PRECEDENT.
# NOTE: this precedent still HOLDS THE GIL (pure-Python exec()); it shows the
# call shape only, not a justification for offloading Python work.
async def _execute(self, code: str, debug: bool = False, **kwargs) -> Any:
    loop = asyncio.get_event_loop()                                       # line 969
    output = await loop.run_in_executor(None, self._execute_code, code, debug)
```

### Does NOT Exist

- ~~`py.allow_threads()` from pure Python~~ — GIL release exists ONLY via the
  Rust extension. Without it, `run_in_executor` gives no parallelism. This is
  the entire reason the "over threshold without Rust → passthrough" rule
  exists; do not "optimize" it away.
- ~~`parrot_codec`~~ — the Rust extension does not exist yet (TASK-1955).
  `rust_available` MUST be `False` in this task's test environment and every
  test must pass in that state.
- ~~An existing circuit breaker in `parrot/`~~ — verify before assuming;
  do not import one from `parrot.core` without confirming it exists.
- ~~A metrics/telemetry service to push p99 into~~ — durations travel in
  `AfterToolCallEvent` (TASK-1952). This module only exposes them.

---

## Implementation Notes

### Pattern to Follow

```python
# The route decision happens BEFORE compressing — that is the point.
def route(self, payload, *, level, codec_name, rust_available):
    if self._breaker.is_open(codec_name):
        return Route.PASSTHROUGH
    if level is FilterLevel.NONE:
        return Route.PASSTHROUGH
    if level is FilterLevel.MINIMAL:
        return Route.INLINE                      # any size, ≤ 0.3 ms budget
    n_bytes, n_rows = estimate_size(payload)
    if n_bytes < self.size_threshold_bytes and n_rows < self.row_threshold:
        return Route.INLINE
    return Route.EXECUTOR if rust_available else Route.PASSTHROUGH
```

### Key Constraints

- `estimate_size` must be **cheap**: serializing 5 MB to decide whether to
  compress 5 MB defeats the purpose. Use `len(payload)` for lists, sample the
  first row and multiply, use `sys.getsizeof` heuristics — and document the
  approximation in the docstring. An over-estimate is safer than an
  under-estimate (it routes to passthrough, which is always correct).
- The breaker is **per codec**, not global: a broken `columnar` must not
  disable `json_compact`.
- Window closes on 100 calls **or** 60 s, whichever comes first. A window with
  zero calls is not "over budget" — it does not advance the consecutive count.
- Half-open: after cooldown, allow exactly one probe call through; if it meets
  budget, close the breaker (re-arm) and log at `info`; if not, reopen and
  restart the cooldown.
- Time source must be injectable (`time_fn` kwarg defaulting to
  `time.monotonic`) so tests do not sleep 5 minutes.
- Thread-safety: `record()` may be called from the executor thread. Guard
  mutable breaker state with a `threading.Lock`.
- No blocking calls, no `await` inside `route()` — it is synchronous and
  called on the loop.

### References in Codebase

- `parrot/_imports.py:84` — `lazy_import`, same pattern used for `faiss` /
  `sentence_transformers`.
- `parrot/tools/pythonrepl.py:969` — `run_in_executor` call shape.

---

## Acceptance Criteria

- [ ] `test_budget_route_decision_pre_compression`: the route is derived from
      the size estimate and the codec is never invoked to decide.
- [ ] `test_no_rust_large_payload_passthrough`: over threshold with
      `rust_available=False` → `Route.PASSTHROUGH` (G9).
- [ ] `test_circuit_breaker_degrades_and_rearms`: 3 consecutive over-budget
      windows → `PASSTHROUGH` + `logger.warning`; re-arms after cooldown via
      a successful probe.
- [ ] Breaker isolation: degrading codec A leaves codec B routable.
- [ ] All defaults match the spec values listed in Scope and are overridable.
- [ ] Every test passes with the Rust extension ABSENT.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/compression/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/compression/`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/compression/test_budget.py
import pytest
from parrot.tools.compression import FilterLevel
from parrot.tools.compression.budget import Route, BudgetRouter


@pytest.fixture
def clock():
    class Clock:
        now = 0.0
        def __call__(self): return self.now
        def advance(self, s): self.now += s
    return Clock()


@pytest.fixture
def router(clock):
    return BudgetRouter(time_fn=clock)


class TestRouting:
    def test_budget_route_decision_pre_compression(self, router):
        big = [{"a": "x" * 100} for _ in range(10_000)]
        # codec is never constructed or called to make this decision
        assert router.route(
            big, level=FilterLevel.NORMAL, codec_name="columnar",
            rust_available=False,
        ) is Route.PASSTHROUGH

    def test_minimal_always_inline(self, router):
        big = [{"a": "x" * 100} for _ in range(10_000)]
        assert router.route(
            big, level=FilterLevel.MINIMAL, codec_name="json_compact",
            rust_available=False,
        ) is Route.INLINE

    def test_no_rust_large_payload_passthrough(self, router):
        big = [{"a": "x" * 100} for _ in range(10_000)]
        assert router.route(big, level=FilterLevel.NORMAL,
                            codec_name="columnar", rust_available=False) is Route.PASSTHROUGH
        assert router.route(big, level=FilterLevel.NORMAL,
                            codec_name="columnar", rust_available=True) is Route.EXECUTOR

    def test_small_payload_inline(self, router):
        small = [{"a": 1} for _ in range(10)]
        assert router.route(small, level=FilterLevel.NORMAL,
                            codec_name="columnar", rust_available=False) is Route.INLINE


class TestCircuitBreaker:
    def test_circuit_breaker_degrades_and_rearms(self, router, clock, caplog):
        small = [{"a": 1} for _ in range(10)]
        for _ in range(3):                       # 3 over-budget windows
            for _ in range(100):
                router.record("columnar", duration_ms=50.0, route=Route.INLINE)
        assert router.route(small, level=FilterLevel.NORMAL,
                            codec_name="columnar", rust_available=False) is Route.PASSTHROUGH
        assert any("columnar" in r.message for r in caplog.records)

        clock.advance(301)                       # cooldown elapsed
        assert router.route(small, level=FilterLevel.NORMAL,
                            codec_name="columnar", rust_available=False) is Route.INLINE
        router.record("columnar", duration_ms=0.2, route=Route.INLINE)
        assert router.route(small, level=FilterLevel.NORMAL,
                            codec_name="columnar", rust_available=False) is Route.INLINE

    def test_breaker_is_per_codec(self, router):
        for _ in range(3):
            for _ in range(100):
                router.record("columnar", duration_ms=50.0, route=Route.INLINE)
        small = [{"a": 1} for _ in range(10)]
        assert router.route(small, level=FilterLevel.MINIMAL,
                            codec_name="json_compact", rust_available=False) is Route.INLINE
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 5, §7 latency framing, G7/G9).
2. **Check dependencies** — TASK-1947 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm `lazy_import` at `_imports.py:84`.
4. **Update status** in `sdd/tasks/index/tool-result-compression.json`.
5. **Implement** per scope.
6. **Verify** acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
