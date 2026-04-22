"""Unit tests for AbstractClient per-loop cache (FEAT-112, TASK-800).

All tests are fully offline — no provider credentials are needed.
Tests verify TASK-795 (base cache), TASK-796 (Google hook), TASK-797 (Grok).
"""
from __future__ import annotations

import asyncio
import gc
import threading

import pytest

from parrot.clients.base import AbstractClient


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

class _StubSDKClient:
    """Minimal fake SDK client returned by get_client() in tests."""

    def __init__(self):
        self.closed: bool = False
        # Unique identity per build to distinguish different instances.
        self.build_id: object = object()

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def stub_sdk_client():
    """Return the _StubSDKClient class (not an instance)."""
    return _StubSDKClient


@pytest.fixture
def counting_abstract_client(stub_sdk_client):
    """A minimal AbstractClient subclass with a get_client() call counter.

    Exposes:
    - ``build_count`` — how many times get_client() was called.
    - ``force_invalid`` — when True, _client_invalid_for_current returns True.
    """
    class _Counter(AbstractClient):
        """Stub AbstractClient for testing the per-loop cache."""

        client_type: str = "test"
        client_name: str = "test"

        def __init__(self, **kw):
            self.build_count: int = 0
            self.force_invalid: bool = False
            super().__init__(**kw)

        async def get_client(self, **_hints):
            """Build and return a fresh stub SDK client."""
            self.build_count += 1
            return stub_sdk_client()

        def _client_invalid_for_current(self, client, **hints) -> bool:
            return self.force_invalid

        async def ask(self, *a, **kw):
            raise NotImplementedError

        async def ask_stream(self, *a, **kw):
            raise NotImplementedError

        async def resume(self, *a, **kw):
            raise NotImplementedError

        async def invoke(self, *a, **kw):
            raise NotImplementedError

    return _Counter


@pytest.fixture
def loop_in_thread():
    """Start a background thread running its own asyncio event loop.

    Yields a ``(submit, loop, thread)`` tuple:
    - ``submit(coro)`` runs the coroutine on the background loop and returns its
      result synchronously (10-second timeout).
    - ``loop`` is the background ``asyncio.AbstractEventLoop``.
    - ``thread`` is the daemon thread.

    Teardown stops the loop and joins the thread.
    """
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


# ---------------------------------------------------------------------------
# Test 1: Same loop reuses the client
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_same_loop_reuses_client(counting_abstract_client):
    """Two _ensure_client() calls on the same loop return the same object."""
    wrapper = counting_abstract_client()
    c1 = await wrapper._ensure_client()
    c2 = await wrapper._ensure_client()
    assert c1 is c2, "Same loop must reuse the cached SDK client."
    assert wrapper.build_count == 1, "get_client() must be called exactly once."


# ---------------------------------------------------------------------------
# Test 2: Different loops build separate clients
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_different_loop_builds_new_client(counting_abstract_client, loop_in_thread):
    """A new event loop must receive a separate SDK client instance."""
    submit, _other_loop, _ = loop_in_thread
    wrapper = counting_abstract_client()

    c_main = await wrapper._ensure_client()
    c_other = submit(wrapper._ensure_client())

    assert c_main is not c_other, "Different loops must get different clients."
    assert wrapper.build_count == 2, "get_client() must be called once per loop."


# ---------------------------------------------------------------------------
# Test 3: Invalidation hook forces rebuild on the same loop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_invalidation_hook_forces_rebuild(counting_abstract_client):
    """When _client_invalid_for_current returns True, the entry is rebuilt."""
    wrapper = counting_abstract_client()
    c1 = await wrapper._ensure_client()
    wrapper.force_invalid = True
    c2 = await wrapper._ensure_client()
    assert c1 is not c2, "Invalidation hook must trigger a new SDK client."
    assert wrapper.build_count == 2


# ---------------------------------------------------------------------------
# Test 4: close() on the current loop awaits the SDK client's close()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_close_on_current_loop_awaits_sdk_close(counting_abstract_client):
    """close() must call the SDK client's async close() and clear the entry."""
    wrapper = counting_abstract_client()
    stub = await wrapper._ensure_client()
    assert stub.closed is False
    await wrapper.close()
    assert stub.closed is True, "SDK client.close() must have been awaited."
    assert wrapper.client is None, "Entry must be cleared after close()."


# ---------------------------------------------------------------------------
# Test 5: close() on a dead loop drops the entry without awaiting
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_close_on_dead_loop_drops_silently(counting_abstract_client, loop_in_thread):
    """close() must drop foreign-loop entries without awaiting their SDK close().

    Note: This test verifies the *foreign-loop* branch of _safe_close_entry()
    (``not is_current_loop``), NOT the dead-weakref branch.  The loop_in_thread
    fixture holds a strong reference to ``other_loop``, so its weakref remains
    alive throughout the test.  The drop-without-await behaviour is triggered
    because the background loop is a *different* loop from the test loop,
    not because the weakref is dead.

    The loop-id-recycling (dead weakref) path is covered separately in
    the integration test ``test_stale_entry_pruned_for_recycled_loop_id``.
    """
    submit, other_loop, _ = loop_in_thread
    wrapper = counting_abstract_client()
    await wrapper._ensure_client()  # entry on the *current* (test) loop

    # Build an entry on the background thread's loop.
    submit(wrapper._ensure_client())
    assert wrapper.build_count == 2  # one entry per loop

    # close() from the still-running (test) loop must not raise even though
    # the background-loop entry cannot be awaited (it's a foreign loop).
    gc.collect()
    await wrapper.close()


# ---------------------------------------------------------------------------
# Test 6: client property returns None before _ensure_client is called
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_client_property_returns_none_before_ensure(counting_abstract_client):
    """The client property must return None on a fresh loop."""
    wrapper = counting_abstract_client()
    assert wrapper.client is None, "client property must be None before _ensure_client()."


# ---------------------------------------------------------------------------
# Test 7: client setter rejects non-None values
# ---------------------------------------------------------------------------

def test_client_setter_rejects_non_none(counting_abstract_client):
    """Assigning a non-None value to .client must raise AttributeError."""
    wrapper = counting_abstract_client()
    with pytest.warns(DeprecationWarning), pytest.raises(AttributeError):
        wrapper.client = object()


# ---------------------------------------------------------------------------
# Test 8: client setter accepts None and clears the current-loop entry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_client_setter_accepts_none_clears_current_loop_entry(
    counting_abstract_client,
):
    """Assigning None to .client clears only the current loop's entry."""
    wrapper = counting_abstract_client()
    await wrapper._ensure_client()
    assert wrapper.client is not None

    wrapper.client = None
    assert wrapper.client is None, "None assignment must clear the current-loop entry."

    # Ensure _ensure_client triggers a rebuild (not a cache hit).
    await wrapper._ensure_client()
    assert wrapper.build_count == 2, "Rebuild must happen after clearing via setter."


# ---------------------------------------------------------------------------
# Test 9: Google-style model-class invalidation hook
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_model_class_invalidates_entry():
    """A hook mirroring GoogleGenAIClient's metadata-comparison logic must
    rebuild when the model class changes and reuse when it stays the same."""

    class _GoogleLike(AbstractClient):
        """Stub that mimics the Google model-class invalidation pattern."""

        client_type: str = "googlelike"
        client_name: str = "googlelike"

        def __init__(self, **kw):
            self.build_count: int = 0
            super().__init__(**kw)

        async def get_client(self, model=None, **_kw):  # noqa: D401
            self.build_count += 1
            return {"model_class": self._classify(model)}

        def _classify(self, model: str | None) -> str:
            return "preview" if model and "preview" in model else "stable"

        def _client_invalid_for_current(self, client, **hints) -> bool:
            loop = self._get_current_loop()
            if loop is None:
                return False
            entry = self._clients_by_loop.get(id(loop))
            if entry is None:
                return True
            desired = self._classify(hints.get("model"))
            return entry.metadata.get("model_class", desired) != desired

        async def _ensure_client(self, model=None, **hints):  # type: ignore[override]
            if model is not None:
                hints["model"] = model
            c = await super()._ensure_client(**hints)
            loop = asyncio.get_running_loop()
            entry = self._clients_by_loop.get(id(loop))
            if entry is not None:
                entry.metadata["model_class"] = self._classify(hints.get("model"))
            return c

        def _filter_get_client_hints(self, **hints) -> dict:
            return {"model": hints["model"]} if "model" in hints else {}

        async def ask(self, *a, **kw):
            raise NotImplementedError

        async def ask_stream(self, *a, **kw):
            raise NotImplementedError

        async def resume(self, *a, **kw):
            raise NotImplementedError

        async def invoke(self, *a, **kw):
            raise NotImplementedError

    w = _GoogleLike()

    # Same model-class → reuse.
    await w._ensure_client(model="gemini-2.5-flash")
    await w._ensure_client(model="gemini-2.5-flash")
    assert w.build_count == 1, "Same model class must reuse the cached client."

    # Different model-class → rebuild.
    await w._ensure_client(model="gemini-3.1-preview")
    assert w.build_count == 2, "Model-class change must rebuild the client."


# ---------------------------------------------------------------------------
# Test 10: Google loop-switch does not invalidate the other loop's entry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_google_loop_switch_does_not_invalidate_other_loop(
    counting_abstract_client, loop_in_thread
):
    """Triggering a model-class change on Loop A must not affect Loop B's entry.

    Expected build sequence: Loop A initial (1), Loop B initial (2),
    Loop A rebuild due to force_invalid=True (3). Loop B count stays at 1.
    """
    submit, _other_loop, _ = loop_in_thread
    wrapper = counting_abstract_client()

    # Build on both loops.
    _c_main = await wrapper._ensure_client()
    _c_other = submit(wrapper._ensure_client())
    assert wrapper.build_count == 2

    # Trigger rebuild on the current loop.
    wrapper.force_invalid = True
    _c_main2 = await wrapper._ensure_client()
    assert wrapper.build_count == 3, "Loop A rebuild must fire (force_invalid=True)."

    # Loop B's entry must still be present and not rebuilt.
    loop_b_id = id(_other_loop)
    assert loop_b_id in wrapper._clients_by_loop, (
        "Loop B's entry must still exist after Loop A rebuild."
    )


# ---------------------------------------------------------------------------
# Test 11: GrokClient.get_client() returns a fresh client each call
# ---------------------------------------------------------------------------

def test_grok_get_client_no_longer_self_caches(monkeypatch):
    """GrokClient.get_client must not cache on self.client; each call gives
    a distinct AsyncClient instance.

    GrokClient has abstract methods that need minimal stubs to be instantiable
    in tests without provider credentials.
    """
    monkeypatch.setenv("XAI_API_KEY", "fake-key-for-test")

    from parrot.clients.grok import GrokClient
    import parrot.clients.grok as _grok_mod

    captured: list = []

    class _StubAsync:
        def __init__(self, **kw):
            captured.append(kw)

        async def close(self):
            pass

    monkeypatch.setattr(_grok_mod, "AsyncClient", _StubAsync)

    # GrokClient has abstract methods; create a concrete subclass for testing.
    class _TestableGrok(GrokClient):
        async def ask(self, *a, **kw):
            raise NotImplementedError

        async def ask_stream(self, *a, **kw):
            raise NotImplementedError

        async def resume(self, *a, **kw):
            raise NotImplementedError

        async def invoke(self, *a, **kw):
            raise NotImplementedError

    async def _check():
        c = _TestableGrok()
        a = await c.get_client()
        b = await c.get_client()
        assert a is not b, "get_client() must return a fresh AsyncClient each call."
        assert len(captured) == 2, "AsyncClient must be instantiated twice."

    asyncio.run(_check())
