# TASK-801: Integration tests — cross-loop reuse + in-loop connection reuse

**Feature**: FEAT-112 — Per-Loop LLM Client Cache
**Spec**: `sdd/specs/per-loop-llm-client-cache.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-800
**Assigned-to**: unassigned

---

## Context

The unit tests in TASK-800 cover the per-loop mechanics with a stub SDK.
This task adds the harder tests from spec §4 Integration Tests:
 - cross-loop invocation mimicking `navigator.background.coroutine_in_thread`;
 - in-loop connection reuse verification;
 - an end-to-end NextStop smoke test marked as an optional integration
   (`@pytest.mark.integration`) that is skipped in CI when Google creds are
   absent.

See spec §4 Integration Tests and §5 Acceptance Criteria (items about
"≥10 consecutive runs" and "no aiohttp-session leaks").

---

## Scope

- Create `packages/ai-parrot/tests/test_per_loop_cache_integration.py` with:

  1. `test_background_task_reuses_cross_loop` — stub-based. Build a wrapper,
     invoke `_ensure_client()` from the main loop and from a thread-spawned
     secondary loop (mimic of `coroutine_in_thread`). Assert two distinct
     SDK clients and no `RuntimeError`.
  2. `test_connection_reuse_within_loop` — stub-based. The stub SDK client
     exposes a fake "connector" counter; N sequential `ask()`-style calls on
     the same wrapper on the same loop must reuse the same SDK client
     instance (no rebuilds). Verified by the `build_count` attribute from the
     counting fixture (see TASK-800) AND by calling the stub's
     `_simulate_request()` counter to ensure the same stub is hit N times.
  3. `test_close_after_cross_loop_use_does_not_raise` — after building
     entries on two loops, closing from the main loop (the secondary loop
     still alive) closes only the current-loop entry normally and drops the
     other one's reference. Closing from the secondary loop afterwards does
     not double-free.
  4. `test_no_aiohttp_session_leak_across_alternating_loops` — stub-only
     proxy for the spec's acceptance criterion. Simulate 50 alternating
     `_ensure_client()` calls across Loop A and Loop B; assert that
     `len(wrapper._clients_by_loop)` stays at exactly 2 and that
     `wrapper.build_count == 2`. (The full 1,000-call leak check with
     `tracemalloc` is a manual verification step, recorded in TASK-802's
     doc as a runbook.)
  5. `test_nextstop_background_task_end_to_end` — marked
     `@pytest.mark.integration`; skipped unless
     `GOOGLE_API_KEY`/`VERTEX_CREDENTIALS_FILE` is available AND the
     `resources/nextstop/` module is importable. Constructs a NextStop-shaped
     agent using the real `GoogleGenAIClient`, invokes it from two different
     threads (each with its own loop) concurrently, asserts no
     "Future attached to a different loop" error across ≥10 runs.

- Fixtures: reuse the `loop_in_thread` and `counting_abstract_client`
  fixtures from TASK-800 (either import or copy locally — keep local to
  avoid cross-test-file coupling).

**NOT in scope**:
- Modifying any production source — this task is tests-only.
- Adding navigator as a test dependency (fixture mimics, does not import it).
- Running the NextStop integration test in CI — it is pure opt-in.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/test_per_loop_cache_integration.py` | CREATE | 4 offline integration tests + 1 opt-in live-ish NextStop test (marker-skipped by default). |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio
import threading
import pytest

from parrot.clients.base import AbstractClient, _LoopClientEntry    # post-TASK-795

# Only imported when the live test is enabled:
# from parrot.clients.google.client import GoogleGenAIClient
# from resources.nextstop.handler import ...  # if/when NextStop module is reachable
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/base.py (post-TASK-795 — same as TASK-800)

class AbstractClient(ABC):
    _clients_by_loop: dict[int, _LoopClientEntry]
    async def _ensure_client(self, **hints: Any) -> Any: ...
    async def close(self) -> None: ...
```

```python
# navigator/background/wrappers/__init__.py (external — for reference only, NOT imported)
def coroutine_in_thread(coro, callback=None, on_complete=None):
    """Run a coroutine in a new thread with a new event loop."""
```

### Does NOT Exist

- ~~`navigator.background.BackgroundService.use_main_loop`~~ — no such flag.
- ~~`pytest.mark.cross_loop`~~ — custom marker; use `pytest.mark.integration` which the project already registers (verify in `pyproject.toml`; if absent, add to an ignore list or register via `pytest.ini_options`).
- ~~`resources.nextstop.handler.NextStopAgent` — may or may not exist depending on repo sync; the test must `pytest.importorskip("resources.nextstop.handler")`.

---

## Implementation Notes

### Pattern to Follow

```python
import pytest, asyncio, threading

@pytest.fixture
def loop_in_thread():
    """(Copy from TASK-800; keep behavior identical.)"""
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    def _run():
        asyncio.set_event_loop(loop)
        ready.set()
        loop.run_forever()
    t = threading.Thread(target=_run, daemon=True)
    t.start(); ready.wait()
    def submit(coro):
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return fut.result(timeout=10)
    try:
        yield submit, loop, t
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=5)
        loop.close()


async def test_background_task_reuses_cross_loop(loop_in_thread):
    from parrot.clients.base import AbstractClient

    class _Wrapper(AbstractClient):
        client_type = "it"; client_name = "it"
        def __init__(self, **kw):
            self.build_count = 0
            super().__init__(**kw)
        async def get_client(self, **_hints):
            self.build_count += 1
            class _C:
                async def close(self): pass
            return _C()
        async def ask(self, *a, **kw): raise NotImplementedError

    submit, other_loop, _ = loop_in_thread
    w = _Wrapper()
    main = await w._ensure_client()
    other = submit(w._ensure_client())
    assert main is not other
    assert w.build_count == 2

    # Close on main loop — must not raise.
    await w.close()


async def test_connection_reuse_within_loop():
    """N calls on the same loop reuse the same SDK client."""
    from parrot.clients.base import AbstractClient

    class _Counter(AbstractClient):
        client_type = "c"; client_name = "c"
        def __init__(self, **kw):
            self.build_count = 0
            super().__init__(**kw)
        async def get_client(self, **_hints):
            self.build_count += 1
            return object()
        async def ask(self, *a, **kw): raise NotImplementedError

    w = _Counter()
    first = await w._ensure_client()
    for _ in range(50):
        got = await w._ensure_client()
        assert got is first
    assert w.build_count == 1


async def test_close_after_cross_loop_use_does_not_raise(loop_in_thread):
    from parrot.clients.base import AbstractClient

    class _Wrapper(AbstractClient):
        client_type = "x"; client_name = "x"
        async def get_client(self, **_hints):
            class _C:
                async def close(self): pass
            return _C()
        async def ask(self, *a, **kw): raise NotImplementedError

    submit, _, _ = loop_in_thread
    w = _Wrapper()
    await w._ensure_client()
    submit(w._ensure_client())
    await w.close()   # must not raise — drops the foreign-loop entry safely


async def test_no_aiohttp_session_leak_across_alternating_loops(loop_in_thread):
    from parrot.clients.base import AbstractClient

    class _W(AbstractClient):
        client_type = "y"; client_name = "y"
        def __init__(self, **kw):
            self.build_count = 0
            super().__init__(**kw)
        async def get_client(self, **_hints):
            self.build_count += 1
            class _C:
                async def close(self): pass
            return _C()
        async def ask(self, *a, **kw): raise NotImplementedError

    submit, _, _ = loop_in_thread
    w = _W()
    for _ in range(25):
        await w._ensure_client()
        submit(w._ensure_client())
    assert w.build_count == 2
    assert len(w._clients_by_loop) == 2


@pytest.mark.integration
async def test_nextstop_background_task_end_to_end():
    """Opt-in live-ish test.

    Requires Google creds + the NextStop module available in the checkout.
    """
    import os
    if not (os.getenv("GOOGLE_API_KEY") or os.getenv("VERTEX_CREDENTIALS_FILE")):
        pytest.skip("No Google credentials configured")
    nextstop = pytest.importorskip("resources.nextstop.handler")
    # Construct a NextStop-shaped agent and run _team_performance via two threads
    # with their own loops; verify zero RuntimeError across 10 consecutive runs.
    # Exact invocation form depends on the current NextStop public API —
    # probe with getattr to stay robust to renames.
    ...
```

### Key Constraints

- The first 4 tests must run in CI without any credentials.
- `test_nextstop_background_task_end_to_end` must be skipped cleanly when
  credentials are absent — do NOT fail or error out.
- If `pyproject.toml` does not already register the `integration` marker,
  add it to the test file's module docstring or `pytest.ini_options` in a
  follow-up — prefer local registration via `pytestmark = pytest.mark.integration`
  on individual tests (never module-wide here — we want the first 4 to run always).

### References in Codebase

- Unit-test counterpart: `packages/ai-parrot/tests/test_per_loop_cache.py`
  (TASK-800).
- Background-thread model we mimic:
  `navigator/background/wrappers/__init__.py` (external, for reference only).

---

## Acceptance Criteria

- [ ] All 5 tests exist; 4 run always, the NextStop test skips without creds.
- [ ] `pytest packages/ai-parrot/tests/test_per_loop_cache_integration.py -v -m "not integration"`
      passes and runs in < 15s.
- [ ] `pytest packages/ai-parrot/tests/test_per_loop_cache_integration.py -v -m integration`
      either skips or passes when creds are available — never errors.
- [ ] No leaked threads or loops (`-x --timeout 30` stays green).
- [ ] `ruff check packages/ai-parrot/tests/test_per_loop_cache_integration.py` is clean.

---

## Test Specification

See Scope — this task IS the integration test module.

---

## Agent Instructions

1. Verify TASK-800 is in `sdd/tasks/completed/`.
2. Read spec §4 Integration Tests + §5 Acceptance Criteria (bullets on
   cross-loop runs and leak verification).
3. Create the integration test file following the patterns above.
4. Run the two pytest invocations in the acceptance criteria.
5. Move this file to `sdd/tasks/completed/`; update the index.
6. Commit: `sdd: TASK-801 — integration tests for per-loop client cache`.

---

## Completion Note

**Completed by**: claude-sonnet-4-6 (sdd-worker)
**Date**: 2026-04-22
**Notes**: All 5 tests created. 4 offline tests pass (<1s). Integration test skips
cleanly without credentials. Local loop_in_thread fixture copied from TASK-800.
Concrete wrapper subclasses used per-test to avoid cross-test coupling.
**Deviations from spec**: None.
