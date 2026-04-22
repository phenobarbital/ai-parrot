# TASK-800: Unit tests for AbstractClient per-loop cache + Google hook

**Feature**: FEAT-112 — Per-Loop LLM Client Cache
**Spec**: `sdd/specs/per-loop-llm-client-cache.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-795, TASK-796, TASK-797
**Assigned-to**: unassigned

---

## Context

TASK-795 introduces the per-loop cache; TASK-796 adds the Google
invalidation hook; TASK-797 strips Grok's self-caching. This task locks in
the behaviour with unit tests that run fully offline using a stub SDK client,
so CI does not require any provider credentials.

See spec §4 (Test Specification → Unit Tests) for the full test matrix.

---

## Scope

Create the test module listed below plus shared fixtures local to it. Do NOT
add provider-level fixtures to the top-level `conftest.py` — keep everything
self-contained.

- Create `packages/ai-parrot/tests/test_per_loop_cache.py` with these tests
  (mapped to the spec matrix):

  1. `test_same_loop_reuses_client` — two `_ensure_client()` calls on the same
     loop return the same object; `get_client()` invoked exactly once.
  2. `test_different_loop_builds_new_client` — on Loop A get client X, on Loop
     B get client Y (`X is not Y`); counter == 2.
  3. `test_invalidation_hook_forces_rebuild` — subclass hook returning `True`
     rebuilds the client for the current loop only; other loops unaffected.
  4. `test_close_on_current_loop_awaits_sdk_close` — `close()` on the current
     loop calls the SDK client's `close()` exactly once; entry removed.
  5. `test_close_on_dead_loop_drops_silently` — GC a secondary loop and assert
     `close()` on the survivor does NOT await the dead loop's client.
  6. `test_client_property_returns_none_before_ensure` — property is `None` on
     a fresh loop that has not called `_ensure_client()`.
  7. `test_client_setter_rejects_non_none` — `wrapper.client = object()` raises
     `AttributeError` with a `DeprecationWarning`.
  8. `test_client_setter_accepts_none_clears_current_loop_entry` — a
     legacy-style `wrapper.client = None` clears only the current-loop entry
     and leaves other loops' entries intact.
  9. `test_google_model_class_invalidates_entry` — simulate
     `GoogleGenAIClient._client_invalid_for_current` behaviour by using a stub
     subclass that mirrors its metadata-comparison logic; switching model on
     the same loop rebuilds, same model on the same loop does not.
  10. `test_google_loop_switch_does_not_invalidate_other_loop` — after running
      on Loops A and B, triggering a model-class change on Loop A does NOT
      rebuild Loop B's entry.
  11. `test_grok_get_client_no_longer_self_caches` — mocked / stubbed
      `AsyncClient` import path; assert `get_client()` returns a fresh
      instance each call and never writes `self.client`.

- Fixtures (in the same file or a colocated `conftest.py` under `tests/` —
  keep local to avoid polluting the global fixture namespace):

  ```python
  @pytest.fixture
  def stub_sdk_client():
      class _StubClient:
          def __init__(self):
              self.closed = False
              self.build_id = object()
          async def close(self):
              self.closed = True
      return _StubClient

  @pytest.fixture
  def counting_abstract_client(stub_sdk_client):
      """A minimal AbstractClient subclass with a get_client call counter."""
      from parrot.clients.base import AbstractClient

      class _Counter(AbstractClient):
          client_type = "test"
          client_name = "test"
          def __init__(self, **kw):
              self.build_count = 0
              self.force_invalid = False
              super().__init__(**kw)
          async def get_client(self, **_hints):
              self.build_count += 1
              return stub_sdk_client()
          def _client_invalid_for_current(self, client, **hints) -> bool:
              return self.force_invalid
          async def ask(self, *a, **kw):
              raise NotImplementedError
      return _Counter

  @pytest.fixture
  def loop_in_thread():
      """Start a background thread running its own asyncio loop.

      Yields (submit, loop, thread). `submit(coro) -> result` runs the
      coroutine synchronously on that loop. Teardown stops and joins.
      """
      import threading, concurrent.futures
      loop = asyncio.new_event_loop()
      ready = threading.Event()
      def _run():
          asyncio.set_event_loop(loop)
          ready.set()
          loop.run_forever()
      t = threading.Thread(target=_run, daemon=True)
      t.start()
      ready.wait()
      def submit(coro):
          fut = asyncio.run_coroutine_threadsafe(coro, loop)
          return fut.result(timeout=10)
      try:
          yield submit, loop, t
      finally:
          loop.call_soon_threadsafe(loop.stop)
          t.join(timeout=5)
          loop.close()
  ```

**NOT in scope**:
- Integration tests that span multiple loops end-to-end (TASK-801).
- Live provider smoke tests (manual only; not in CI).
- Documentation (TASK-802).
- Touching real SDK installations (anthropic, openai, google-genai, xai-sdk).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/test_per_loop_cache.py` | CREATE | 11 unit tests per spec §4 matrix. All tests must be offline-only (stubbed SDK). |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio
import gc
import threading
import weakref

import pytest

# Under test — post-TASK-795:
from parrot.clients.base import AbstractClient, _LoopClientEntry

# For the Grok-specific test — post-TASK-797:
from parrot.clients.grok import GrokClient
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/base.py (post-TASK-795)

class AbstractClient(ABC):
    _clients_by_loop: dict[int, _LoopClientEntry]
    _locks_by_loop: dict[int, asyncio.Lock]

    @property
    def client(self) -> Optional[Any]: ...
    @client.setter
    def client(self, value: Optional[Any]) -> None: ...

    async def _ensure_client(self, **hints: Any) -> Any: ...
    def _client_invalid_for_current(self, client, **hints) -> bool: ...
    async def close(self) -> None: ...
    async def close_all(self) -> None: ...
    async def _close_current_loop_entry(self) -> None: ...

@dataclass
class _LoopClientEntry:
    client: Any
    loop_ref: "ReferenceType"
    metadata: dict
```

```python
# packages/ai-parrot/src/parrot/clients/grok.py (post-TASK-797)
class GrokClient(AbstractClient):
    async def get_client(self) -> AsyncClient: ...   # returns fresh client
```

### Does NOT Exist

- ~~`parrot.clients.base.ClientCache`~~ — no class of that name.
- ~~`AbstractClient.loop_id`~~ — no such attribute.
- ~~`pytest.mark.asyncio_event_loop`~~ — use `pytest.mark.asyncio` (with `asyncio_mode = "auto"` if configured, otherwise explicit marker).

---

## Implementation Notes

### Test patterns

Use `pytest.mark.asyncio` for coroutine tests. Check `pyproject.toml` for the
project's asyncio mode; if `auto`, the marker is optional.

Critical patterns:

```python
import pytest, asyncio, threading

async def test_same_loop_reuses_client(counting_abstract_client):
    wrapper = counting_abstract_client()
    c1 = await wrapper._ensure_client()
    c2 = await wrapper._ensure_client()
    assert c1 is c2
    assert wrapper.build_count == 1

async def test_different_loop_builds_new_client(counting_abstract_client, loop_in_thread):
    submit, other_loop, _ = loop_in_thread
    wrapper = counting_abstract_client()
    c_main = await wrapper._ensure_client()
    c_other = submit(wrapper._ensure_client())
    assert c_main is not c_other
    assert wrapper.build_count == 2

async def test_invalidation_hook_forces_rebuild(counting_abstract_client):
    wrapper = counting_abstract_client()
    c1 = await wrapper._ensure_client()
    wrapper.force_invalid = True
    c2 = await wrapper._ensure_client()
    assert c1 is not c2
    assert wrapper.build_count == 2

async def test_close_on_current_loop_awaits_sdk_close(counting_abstract_client):
    wrapper = counting_abstract_client()
    stub = await wrapper._ensure_client()
    assert stub.closed is False
    await wrapper.close()
    assert stub.closed is True
    assert wrapper.client is None

async def test_close_on_dead_loop_drops_silently(counting_abstract_client):
    """Entries whose loop is no longer alive must be dropped without awaiting."""
    import gc
    wrapper = counting_abstract_client()
    await wrapper._ensure_client()  # entry on current loop

    # Build an entry on a second loop, then let that loop be GC'd.
    other_loop = asyncio.new_event_loop()
    try:
        other_loop.run_until_complete(wrapper._ensure_client())
    finally:
        other_loop.close()
    del other_loop
    gc.collect()

    # Now close from the still-alive loop — must NOT raise.
    await wrapper.close()

def test_client_setter_rejects_non_none(counting_abstract_client):
    wrapper = counting_abstract_client()
    with pytest.warns(DeprecationWarning), pytest.raises(AttributeError):
        wrapper.client = object()

async def test_client_setter_accepts_none_clears_current_loop_entry(counting_abstract_client):
    wrapper = counting_abstract_client()
    await wrapper._ensure_client()
    assert wrapper.client is not None
    wrapper.client = None
    assert wrapper.client is None
    # And _ensure_client rebuilds:
    await wrapper._ensure_client()
    assert wrapper.build_count == 2

async def test_google_model_class_invalidates_entry():
    """Simulate the Google hook via a stub subclass mirroring its logic."""
    from parrot.clients.base import AbstractClient

    class _GoogleLike(AbstractClient):
        client_type = "googlelike"; client_name = "googlelike"
        def __init__(self, **kw):
            self.build_count = 0
            super().__init__(**kw)
        async def get_client(self, model=None):
            self.build_count += 1
            return {"model_class": self._classify(model)}
        def _classify(self, model):
            return "preview" if model and "preview" in model else "stable"
        def _client_invalid_for_current(self, client, **hints) -> bool:
            loop = self._get_current_loop()
            entry = self._clients_by_loop.get(id(loop)) if loop else None
            if entry is None:
                return True
            desired = self._classify(hints.get("model"))
            return entry.metadata.get("model_class", desired) != desired
        async def _ensure_client(self, model=None, **hints):
            if model is not None:
                hints["model"] = model
            c = await super()._ensure_client(**hints)
            loop = asyncio.get_running_loop()
            entry = self._clients_by_loop.get(id(loop))
            if entry is not None:
                entry.metadata["model_class"] = self._classify(hints.get("model"))
            return c
        def _filter_get_client_hints(self, **hints):
            return {"model": hints["model"]} if "model" in hints else {}
        async def ask(self, *a, **kw): raise NotImplementedError

    w = _GoogleLike()
    await w._ensure_client(model="gemini-2.5-flash")
    await w._ensure_client(model="gemini-2.5-flash")
    assert w.build_count == 1
    await w._ensure_client(model="gemini-3.1-preview")
    assert w.build_count == 2

async def test_google_loop_switch_does_not_invalidate_other_loop(loop_in_thread):
    # Build on Loop A + Loop B with same model, then change model on Loop A.
    # Loop B's entry must stay (build_count == 3: A-initial, B-initial, A-rebuild).
    ...

def test_grok_get_client_no_longer_self_caches(monkeypatch):
    """Ensure GrokClient.get_client does not cache on self.client."""
    import os
    monkeypatch.setenv("XAI_API_KEY", "fake-key-for-test")
    from parrot.clients.grok import GrokClient

    async def _check():
        c = GrokClient()
        # Patch the xai_sdk.AsyncClient symbol imported by grok.py.
        from parrot.clients import grok as _grok_mod
        captured = []
        class _StubAsync:
            def __init__(self, **kw): captured.append(kw)
            async def close(self): pass
        monkeypatch.setattr(_grok_mod, "AsyncClient", _StubAsync)
        a = await c.get_client()
        b = await c.get_client()
        assert a is not b, "get_client must return a fresh AsyncClient each call"
    asyncio.run(_check())
```

### Key Constraints

- No network calls. No provider credentials.
- Tests MUST clean up their secondary loops/threads in `finally` blocks
  (use the `loop_in_thread` fixture which handles teardown).
- Use `gc.collect()` deliberately in the dead-loop test to trigger the
  weakref invalidation path.
- `pytest.warns(DeprecationWarning)` + `pytest.raises(AttributeError)` nest
  in that order (the warning fires before the raise).

### References in Codebase

- Pattern for pytest-asyncio in this repo: see `tests/test_anthropic_client.py`.
- Pattern for stubbing provider SDKs: see `tests/test_grok_client.py`.

---

## Acceptance Criteria

- [ ] All 11 tests listed in Scope exist and pass.
- [ ] `pytest packages/ai-parrot/tests/test_per_loop_cache.py -v` runs in < 10s.
- [ ] No test requires real provider credentials.
- [ ] No test leaks a thread/loop (run with `-x --timeout 30` — no hanging).
- [ ] `ruff check packages/ai-parrot/tests/test_per_loop_cache.py` is clean.

---

## Test Specification

See Scope — the task itself IS the test module. The Scope enumerates the
acceptance-criterion test list.

---

## Agent Instructions

1. Verify TASK-795, TASK-796, TASK-797 are in `sdd/tasks/completed/`.
2. Read spec §4 (Test Specification) in full.
3. Inspect `pyproject.toml` for the pytest-asyncio mode setting (`auto` or
   `strict`) and structure the marker usage accordingly.
4. Create the test file, copy the fixtures block verbatim, and implement each
   of the 11 tests.
5. Run `pytest packages/ai-parrot/tests/test_per_loop_cache.py -v` and
   iterate until green.
6. Move this file to `sdd/tasks/completed/`; update the index.
7. Commit: `sdd: TASK-800 — unit tests for per-loop client cache`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:
**Deviations from spec**:
