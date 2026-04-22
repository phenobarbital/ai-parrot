# TASK-831: Observability Hooks for Storage Backends

**Feature**: FEAT-116 — Pluggable Storage Backends for Conversations & Artifacts
**Spec**: `sdd/specs/dynamodb-fallback-redis.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-822, TASK-824, TASK-826, TASK-827, TASK-828
**Assigned-to**: unassigned

---

## Context

Per the spec's Open Question #6 (answered "add on this scope"), v1 must
expose optional observability hooks so a Grafana dashboard (or equivalent)
can compare per-backend per-method latency and error rates. The design must
be low-cost: no required metrics library, no forced collector, just a clean
seam that production setups can wire up.

This is an ADDITION to the original spec (the open-question answer flipped
it from "out of scope" to "in scope"). Keep the scope minimal: a protocol,
default no-op, and a decorator that can wrap any `ConversationBackend`.

---

## Scope

- Create `packages/ai-parrot/src/parrot/storage/metrics.py` with:
  - A `StorageMetrics` `typing.Protocol` exposing two callables:
    - `record_latency(backend_name: str, method: str, duration_ms: float) -> None`
    - `record_error(backend_name: str, method: str, error_type: str) -> None`
  - A `NoopStorageMetrics` concrete no-op implementation.
- Create `packages/ai-parrot/src/parrot/storage/instrumented.py` with:
  - `InstrumentedBackend(ConversationBackend)` — a wrapper class that takes another `ConversationBackend` plus a `StorageMetrics` instance, and delegates every abstract method while recording latency/errors.
  - Wrap every method named in the ABC that returns a coroutine (all 11 CRUD + `initialize`/`close`; skip `is_connected` since it is a property and synchronous).
- Extend the factory from TASK-829 to optionally wrap the selected backend in `InstrumentedBackend` when `PARROT_STORAGE_METRICS` is set to a module path pointing at a `StorageMetrics` instance (default: no wrapping).
- Add `PARROT_STORAGE_METRICS` to `parrot/conf.py` (e.g. `"myapp.metrics:storage_metrics"`). Default `None` → no wrapping.
- Add a helper in `parrot/storage/backends/__init__.py`: `load_metrics_from_path(path: str) -> StorageMetrics` that imports the given `module:attribute` and returns the instance, or raises `RuntimeError` on failure.
- Write unit tests at `packages/ai-parrot/tests/storage/test_instrumented_backend.py`:
  - `NoopStorageMetrics` records do nothing.
  - `InstrumentedBackend` delegates to the wrapped backend correctly (round-trip a `put_thread` / `query_threads`).
  - `InstrumentedBackend.put_thread` calls `metrics.record_latency(...)` exactly once on success.
  - `InstrumentedBackend.put_thread` calls `metrics.record_error(...)` when the inner backend raises, and re-raises.
  - Factory with `PARROT_STORAGE_METRICS=tests.fixtures.metrics:METRICS` wraps the backend; default leaves it bare.

**NOT in scope**: Providing any Prometheus / OpenTelemetry / statsd integration. Histograms, counters, exemplars — users plug those in through the protocol. Contract test re-run with instrumented backends (the existing suite exercises bare backends; an extra pass with an instrumented wrapper is a nice-to-have, not required).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/storage/metrics.py` | CREATE | `StorageMetrics` Protocol + `NoopStorageMetrics` |
| `packages/ai-parrot/src/parrot/storage/instrumented.py` | CREATE | `InstrumentedBackend` wrapper |
| `packages/ai-parrot/src/parrot/storage/backends/__init__.py` | MODIFY | Add `load_metrics_from_path` helper; update factory to optionally wrap |
| `packages/ai-parrot/src/parrot/storage/__init__.py` | MODIFY | Re-export the new types |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Add `PARROT_STORAGE_METRICS` |
| `packages/ai-parrot/tests/storage/test_instrumented_backend.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import importlib
import time
from typing import Any, List, Optional, Protocol, runtime_checkable

from navconfig.logging import logging

from parrot.storage.backends.base import ConversationBackend   # from TASK-822
```

### Existing Signatures to Use

```python
# parrot/storage/backends/base.py (from TASK-822)
class ConversationBackend(ABC):
    # all 14 abstract members — InstrumentedBackend must delegate every one.
```

### Does NOT Exist

- ~~An existing `parrot.metrics` module or base class~~ — this task creates the first dedicated storage metrics seam.
- ~~Prometheus / OpenTelemetry helpers in this project~~ — NOT imported; leave instrumentation to the user's adapter.
- ~~A `StorageMetrics.observe` or `.counter` method~~ — the protocol has exactly `record_latency` and `record_error`.
- ~~An `@instrumented` decorator for individual methods~~ — the wrapper class is enough; don't build two abstractions.

---

## Implementation Notes

### Protocol

```python
# parrot/storage/metrics.py
from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageMetrics(Protocol):
    """Protocol for storage-backend metric collection.

    Implementers plug in Prometheus / OpenTelemetry / statsd in their own code.
    AI-Parrot ships a no-op default and an InstrumentedBackend wrapper that
    calls these methods around every backend operation.
    """

    def record_latency(
        self, backend_name: str, method: str, duration_ms: float,
    ) -> None: ...

    def record_error(
        self, backend_name: str, method: str, error_type: str,
    ) -> None: ...


class NoopStorageMetrics:
    """Default: records nothing."""

    def record_latency(self, backend_name, method, duration_ms): ...
    def record_error(self, backend_name, method, error_type): ...
```

### Wrapper

```python
# parrot/storage/instrumented.py
import time
from typing import List, Optional

from parrot.storage.backends.base import ConversationBackend
from parrot.storage.metrics import StorageMetrics, NoopStorageMetrics


class InstrumentedBackend(ConversationBackend):
    """Wraps any ConversationBackend and records per-method latency + errors."""

    def __init__(
        self, inner: ConversationBackend, metrics: Optional[StorageMetrics] = None,
    ) -> None:
        self._inner = inner
        self._metrics = metrics or NoopStorageMetrics()
        self._name = type(inner).__name__

    # --- Lifecycle ---
    async def initialize(self) -> None:
        await self._measure("initialize", self._inner.initialize)

    async def close(self) -> None:
        await self._measure("close", self._inner.close)

    @property
    def is_connected(self) -> bool:
        return self._inner.is_connected

    def build_overflow_prefix(self, user_id, agent_id, session_id, artifact_id) -> str:
        return self._inner.build_overflow_prefix(user_id, agent_id, session_id, artifact_id)

    # --- Threads / Turns / Artifacts ---
    async def put_thread(self, *a, **kw):          return await self._measure("put_thread", self._inner.put_thread, *a, **kw)
    async def update_thread(self, *a, **kw):       return await self._measure("update_thread", self._inner.update_thread, *a, **kw)
    async def query_threads(self, *a, **kw):       return await self._measure("query_threads", self._inner.query_threads, *a, **kw)
    async def put_turn(self, *a, **kw):            return await self._measure("put_turn", self._inner.put_turn, *a, **kw)
    async def query_turns(self, *a, **kw):         return await self._measure("query_turns", self._inner.query_turns, *a, **kw)
    async def delete_turn(self, *a, **kw):         return await self._measure("delete_turn", self._inner.delete_turn, *a, **kw)
    async def delete_thread_cascade(self, *a, **kw):   return await self._measure("delete_thread_cascade", self._inner.delete_thread_cascade, *a, **kw)
    async def put_artifact(self, *a, **kw):        return await self._measure("put_artifact", self._inner.put_artifact, *a, **kw)
    async def get_artifact(self, *a, **kw):        return await self._measure("get_artifact", self._inner.get_artifact, *a, **kw)
    async def query_artifacts(self, *a, **kw):     return await self._measure("query_artifacts", self._inner.query_artifacts, *a, **kw)
    async def delete_artifact(self, *a, **kw):     return await self._measure("delete_artifact", self._inner.delete_artifact, *a, **kw)
    async def delete_session_artifacts(self, *a, **kw):  return await self._measure("delete_session_artifacts", self._inner.delete_session_artifacts, *a, **kw)

    # --- Internals ---
    async def _measure(self, method: str, fn, *a, **kw):
        t0 = time.perf_counter()
        try:
            return await fn(*a, **kw)
        except Exception as exc:
            self._metrics.record_error(self._name, method, type(exc).__name__)
            raise
        finally:
            duration_ms = (time.perf_counter() - t0) * 1000.0
            self._metrics.record_latency(self._name, method, duration_ms)
```

### Factory Extension

```python
# parrot/storage/backends/__init__.py (MODIFY)
import importlib
from typing import Optional

from parrot.storage.metrics import StorageMetrics
from parrot.storage.instrumented import InstrumentedBackend


def load_metrics_from_path(path: str) -> StorageMetrics:
    module_name, _, attr = path.partition(":")
    if not module_name or not attr:
        raise RuntimeError(f"Invalid PARROT_STORAGE_METRICS path: {path!r}")
    try:
        mod = importlib.import_module(module_name)
        obj = getattr(mod, attr)
    except Exception as exc:
        raise RuntimeError(f"Failed to import metrics from {path!r}: {exc}") from exc
    return obj


async def build_conversation_backend(override: Optional[str] = None):
    # ... existing body from TASK-829 that selects the concrete backend ...
    backend = ...  # concrete backend as today

    # NEW: optional instrumentation
    from parrot.conf import PARROT_STORAGE_METRICS
    if PARROT_STORAGE_METRICS:
        metrics = load_metrics_from_path(PARROT_STORAGE_METRICS)
        backend = InstrumentedBackend(backend, metrics=metrics)
    return backend
```

### Key Constraints

- **Zero cost when unused**: if `PARROT_STORAGE_METRICS` is unset, the factory returns the raw backend — no wrapper, no overhead.
- **Correctness over cleverness**: the wrapper MUST delegate every abstract method; missing one would silently bypass instrumentation.
- **Preserve errors**: `_measure` re-raises the original exception after recording. Do not swallow.
- **`build_overflow_prefix` is concrete and sync** — delegate directly, no timing (it's a pure string format).
- **`is_connected` is a property** — delegate directly, no timing.
- **Use `time.perf_counter()`**: monotonic and high-resolution; do not use `time.time()`.
- **Naming**: metric method argument `backend_name` is `type(inner).__name__` — e.g., `"ConversationSQLiteBackend"`.

### References in Codebase

- `parrot/storage/backends/base.py` (TASK-822) — authoritative method list.
- `parrot/storage/backends/__init__.py` (after TASK-829) — host of the factory.
- Stdlib `typing.Protocol` — no external dep needed.

---

## Acceptance Criteria

- [ ] `parrot/storage/metrics.py` exports `StorageMetrics` (Protocol) and `NoopStorageMetrics`.
- [ ] `parrot/storage/instrumented.py` exports `InstrumentedBackend(ConversationBackend)` wrapping any backend.
- [ ] `InstrumentedBackend` instruments every async abstract method in the ABC; `is_connected` and `build_overflow_prefix` pass through without timing.
- [ ] On successful call → `record_latency` is called once. On exception → `record_error` is called once AND exception is re-raised.
- [ ] `PARROT_STORAGE_METRICS` config added to `parrot/conf.py`.
- [ ] Factory (from TASK-829) wraps the backend when `PARROT_STORAGE_METRICS` is set; leaves it bare otherwise.
- [ ] `load_metrics_from_path("pkg.mod:ATTR")` imports and returns the attribute; bad paths raise `RuntimeError`.
- [ ] All existing storage tests still pass.
- [ ] New tests pass: `pytest packages/ai-parrot/tests/storage/test_instrumented_backend.py -v`.

---

## Test Specification

```python
# packages/ai-parrot/tests/storage/test_instrumented_backend.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.storage.backends.base import ConversationBackend
from parrot.storage.metrics import NoopStorageMetrics
from parrot.storage.instrumented import InstrumentedBackend


class _CountingMetrics:
    def __init__(self):
        self.latency_calls = []
        self.error_calls = []
    def record_latency(self, backend, method, ms):
        self.latency_calls.append((backend, method, ms))
    def record_error(self, backend, method, err):
        self.error_calls.append((backend, method, err))


class _Stub(ConversationBackend):
    async def initialize(self): ...
    async def close(self): ...
    @property
    def is_connected(self): return True
    async def put_thread(self, *a, **kw): return None
    async def update_thread(self, *a, **kw): ...
    async def query_threads(self, *a, **kw): return []
    async def put_turn(self, *a, **kw): ...
    async def query_turns(self, *a, **kw): return []
    async def delete_turn(self, *a, **kw): return True
    async def delete_thread_cascade(self, *a, **kw): return 0
    async def put_artifact(self, *a, **kw): raise RuntimeError("boom")
    async def get_artifact(self, *a, **kw): return None
    async def query_artifacts(self, *a, **kw): return []
    async def delete_artifact(self, *a, **kw): ...
    async def delete_session_artifacts(self, *a, **kw): return 0


@pytest.mark.asyncio
async def test_noop_metrics_does_nothing():
    m = NoopStorageMetrics()
    m.record_latency("b", "m", 1.0)
    m.record_error("b", "m", "E")


@pytest.mark.asyncio
async def test_records_latency_on_success():
    metrics = _CountingMetrics()
    b = InstrumentedBackend(_Stub(), metrics=metrics)
    await b.put_thread("u", "a", "s", {"t": "x"})
    assert len(metrics.latency_calls) == 1
    name, method, ms = metrics.latency_calls[0]
    assert method == "put_thread"
    assert ms >= 0


@pytest.mark.asyncio
async def test_records_error_and_reraises():
    metrics = _CountingMetrics()
    b = InstrumentedBackend(_Stub(), metrics=metrics)
    with pytest.raises(RuntimeError, match="boom"):
        await b.put_artifact("u", "a", "s", "aid", {})
    assert len(metrics.error_calls) == 1
    assert metrics.error_calls[0][1] == "put_artifact"


def test_is_connected_passes_through():
    b = InstrumentedBackend(_Stub())
    assert b.is_connected is True


def test_build_overflow_prefix_passes_through():
    b = InstrumentedBackend(_Stub())
    assert b.build_overflow_prefix("u", "a", "s", "aid") == "artifacts/USER#u#AGENT#a/THREAD#s/aid"


def test_load_metrics_from_path_bad_path():
    from parrot.storage.backends import load_metrics_from_path
    with pytest.raises(RuntimeError):
        load_metrics_from_path("nonexistent.module:THING")
    with pytest.raises(RuntimeError):
        load_metrics_from_path("invalid-format")
```

---

## Agent Instructions

When you pick up this task:

1. **Read** the spec's Open Question #6 and the user's accept ("add on this scope").
2. **Check dependencies** — TASK-822 at minimum; TASK-829 is required to extend the factory (complete it first if not done).
3. **Verify the Codebase Contract**.
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
5. **Implement** in order: `metrics.py` → `instrumented.py` → factory extension → conf.py → tests.
6. **Run tests**: `source .venv/bin/activate && pytest packages/ai-parrot/tests/storage/test_instrumented_backend.py -v`.
7. Also re-run the full storage suite to confirm no regression: `pytest packages/ai-parrot/tests/storage/ -v`.
8. **Move** this file to `sdd/tasks/completed/`.
9. **Update index** → `"done"`.
10. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
