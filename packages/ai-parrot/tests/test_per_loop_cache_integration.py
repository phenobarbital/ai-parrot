"""Integration tests for AbstractClient per-loop cache (FEAT-112, TASK-801).

Tests 1-4 are fully offline (stub SDK, no credentials required).
Test 5 is opt-in: marked ``@pytest.mark.integration`` and skipped in CI
unless Google credentials are configured.

These tests verify cross-loop reuse scenarios that mirror real production
usage (e.g. navigator.background.coroutine_in_thread spawning a fresh loop
from a background thread).
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from parrot.clients.base import AbstractClient


# ---------------------------------------------------------------------------
# Local fixtures (kept self-contained per task spec)
# ---------------------------------------------------------------------------


@pytest.fixture
def loop_in_thread():
    """Start a background thread running its own asyncio event loop.

    Yields a ``(submit, loop, thread)`` tuple:
    - ``submit(coro)`` runs the coroutine on the background loop and returns
      its result synchronously (10-second timeout).
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
# Helper: minimal concrete AbstractClient subclasses (one per test)
# ---------------------------------------------------------------------------

def _make_wrapper(client_type: str = "it", client_name: str = "it"):
    """Factory returning a concrete AbstractClient subclass with a build counter."""

    class _Wrapper(AbstractClient):
        client_type = "it"  # noqa: RUF012
        client_name = "it"  # noqa: RUF012

        def __init__(self, **kw):
            self.build_count: int = 0
            super().__init__(**kw)

        async def get_client(self, **_hints):
            self.build_count += 1

            class _FakeClient:
                async def close(self):
                    pass

            return _FakeClient()

        async def ask(self, *a, **kw):
            raise NotImplementedError

        async def ask_stream(self, *a, **kw):
            raise NotImplementedError

        async def resume(self, *a, **kw):
            raise NotImplementedError

        async def invoke(self, *a, **kw):
            raise NotImplementedError

    _Wrapper.client_type = client_type
    _Wrapper.client_name = client_name
    return _Wrapper


# ---------------------------------------------------------------------------
# Test 1: Cross-loop invocation mimicking coroutine_in_thread
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_background_task_reuses_cross_loop(loop_in_thread):
    """Simulate navigator.background.coroutine_in_thread — each loop gets its
    own SDK client with no RuntimeError.
    """
    submit, _other_loop, _ = loop_in_thread
    _Wrapper = _make_wrapper("it1", "it1")

    w = _Wrapper()
    main_client = await w._ensure_client()
    other_client = submit(w._ensure_client())

    assert main_client is not other_client, (
        "Cross-loop calls must return distinct SDK clients."
    )
    assert w.build_count == 2, (
        "get_client() must be called exactly once per loop."
    )

    # Closing from the main loop must not raise for the foreign loop's entry.
    await w.close()


# ---------------------------------------------------------------------------
# Test 2: In-loop connection reuse
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connection_reuse_within_loop():
    """50 sequential _ensure_client() calls on the same loop reuse the same SDK
    client (build_count stays at 1).
    """
    _Wrapper = _make_wrapper("it2", "it2")

    w = _Wrapper()
    first = await w._ensure_client()
    for i in range(50):
        got = await w._ensure_client()
        assert got is first, f"Iteration {i}: expected cache hit, got new client."

    assert w.build_count == 1, "Only one SDK client must be built per loop."


# ---------------------------------------------------------------------------
# Test 3: close() after cross-loop use does not raise
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_close_after_cross_loop_use_does_not_raise(loop_in_thread):
    """After building entries on two loops, closing from the main loop must
    silently drop the foreign-loop entry and fully tear down the current-loop
    entry.  A second close call afterwards is safe.
    """
    submit, _other_loop, _ = loop_in_thread
    _Wrapper = _make_wrapper("it3", "it3")

    w = _Wrapper()
    await w._ensure_client()
    submit(w._ensure_client())
    assert w.build_count == 2

    # Close from the main loop — must not raise.
    await w.close()
    assert w.client is None, "Current loop entry must be cleared after close()."

    # Second close (all entries already gone) must also not raise.
    await w.close()


# ---------------------------------------------------------------------------
# Test 4: No per-loop client leak across alternating loops
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_aiohttp_session_leak_across_alternating_loops(loop_in_thread):
    """50 alternating _ensure_client() calls across two loops must not create
    more than 2 per-loop entries (one per loop) and must not call get_client()
    more than 2 times.
    """
    submit, _other_loop, _ = loop_in_thread
    _Wrapper = _make_wrapper("it4", "it4")

    w = _Wrapper()
    for _ in range(25):
        await w._ensure_client()        # main loop (always cache hit after 1st)
        submit(w._ensure_client())      # background loop (always cache hit after 1st)

    assert w.build_count == 2, (
        f"Expected exactly 2 builds (one per loop), got {w.build_count}."
    )
    assert len(w._clients_by_loop) == 2, (
        f"Expected exactly 2 cache entries, got {len(w._clients_by_loop)}."
    )


# ---------------------------------------------------------------------------
# Test 5: NextStop end-to-end (opt-in integration, skipped in CI)
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_nextstop_background_task_end_to_end():
    """Opt-in live test: requires Google credentials.

    Skipped unless ``GOOGLE_API_KEY`` or ``VERTEX_CREDENTIALS_FILE`` is set
    AND the NextStop module is importable.

    Constructs a NextStop-shaped agent using the real GoogleGenAIClient and
    invokes it concurrently from two threads, each with its own event loop,
    verifying zero RuntimeError across 10 consecutive invocations.
    """
    import os

    if not (os.getenv("GOOGLE_API_KEY") or os.getenv("VERTEX_CREDENTIALS_FILE")):
        pytest.skip("No Google credentials configured — skipping NextStop e2e test.")

    # Probe for the optional NextStop module without hard-importing it.
    pytest.importorskip(
        "resources.nextstop.handler",
        reason="NextStop module not available in this checkout — skipping e2e test.",
    )

    from parrot.clients.google.client import GoogleGenAIClient

    agent = GoogleGenAIClient()
    errors: list[Exception] = []

    def _run_in_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            for _ in range(10):
                loop.run_until_complete(agent._ensure_client())
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            loop.run_until_complete(agent._close_current_loop_entry())
            loop.close()

    t1 = threading.Thread(target=_run_in_thread, daemon=True)
    t2 = threading.Thread(target=_run_in_thread, daemon=True)
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert not errors, f"Cross-loop errors: {errors}"
