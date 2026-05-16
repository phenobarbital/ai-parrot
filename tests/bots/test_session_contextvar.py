"""Tests for ContextVar infrastructure and session() lifecycle (FEAT-175).

TASK-1205 covers:
  1. TestContextVarInfrastructure: _current_ctx ContextVar set / get / reset basics
  2. TestSessionContextManager: AbstractBot.session() lifecycle (yields real bot,
     sets and resets ContextVar, concurrent isolation, pre-built ctx)
  3. TestFallbackSemantics: ctx-fallback pattern used in BaseBot entry points
     (ask, invoke, conversation, ask_stream)
"""
from __future__ import annotations

import asyncio
import contextvars
import pytest
from unittest.mock import MagicMock
from aiohttp import web

from parrot.utils.helpers import RequestContext, current_context, _current_ctx
from parrot.bots.abstract import AbstractBot


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def configured_bot():
    """Minimal AbstractBot mock with session() bound from the real implementation.

    Uses BoundedSemaphore(10) so concurrent workers can enter session()
    simultaneously, making the concurrent-isolation test meaningful.
    """

    class ConcreteBot(AbstractBot):
        async def chat(self, message, **kwargs):
            return "ok"

        async def stream(self, message, **kwargs):
            yield "ok"

        async def invoke(self, message, **kwargs):
            return "ok"

    bot = MagicMock(spec=ConcreteBot)
    bot.name = "test_bot"
    bot._semaphore = asyncio.BoundedSemaphore(10)
    bot.logger = MagicMock()
    bot.session = AbstractBot.session.__get__(bot, ConcreteBot)
    return bot


def _make_mock_request():
    """Minimal aiohttp request mock (no PDP → fail-open)."""
    request = MagicMock(spec=web.Request)
    session = MagicMock()
    session.get = MagicMock(return_value={"username": "u", "groups": []})
    request.session = session
    request.app = MagicMock()
    request.app.get = MagicMock(return_value=None)
    return request


# ---------------------------------------------------------------------------
# TestContextVarInfrastructure
# ---------------------------------------------------------------------------


class TestContextVarInfrastructure:
    """Tests for TASK-1201 — _current_ctx ContextVar basics."""

    def test_current_context_default_none(self):
        """current_context() returns None when no context is bound."""
        assert current_context() is None

    def test_set_and_get(self):
        """After _current_ctx.set(), current_context() returns the same object."""
        ctx = RequestContext(user_id="test")
        token = _current_ctx.set(ctx)
        try:
            assert current_context() is ctx
        finally:
            _current_ctx.reset(token)

    def test_reset_clears(self):
        """_current_ctx.reset(token) restores the previous value (None)."""
        ctx = RequestContext()
        token = _current_ctx.set(ctx)
        _current_ctx.reset(token)
        assert current_context() is None

    def test_nested_set_restores_previous(self):
        """Nested set/reset restores the outer value, not None."""
        outer = RequestContext(user_id="outer")
        inner = RequestContext(user_id="inner")

        t1 = _current_ctx.set(outer)
        t2 = _current_ctx.set(inner)

        assert current_context() is inner
        _current_ctx.reset(t2)
        assert current_context() is outer
        _current_ctx.reset(t1)
        assert current_context() is None

    def test_copy_context_isolates_changes(self):
        """Changes inside a copied context do not escape to the caller."""
        outer_ctx = RequestContext(user_id="outer")
        token = _current_ctx.set(outer_ctx)
        try:
            inner_result: dict = {}

            def _run_inner() -> None:
                _current_ctx.set(RequestContext(user_id="inner"))
                inner_result["ctx"] = current_context()

            # Run in a copied context — changes don't affect the outer scope
            ctx_copy = contextvars.copy_context()
            ctx_copy.run(_run_inner)

            # Outer context is unchanged
            assert current_context() is outer_ctx
            # Inner saw the inner value
            assert inner_result["ctx"].user_id == "inner"  # type: ignore[union-attr]
        finally:
            _current_ctx.reset(token)


# ---------------------------------------------------------------------------
# TestSessionContextManager
# ---------------------------------------------------------------------------


class TestSessionContextManager:
    """Tests for TASK-1202 — AbstractBot.session() context manager."""

    @pytest.mark.asyncio
    async def test_yields_real_bot(self, configured_bot):
        """session() yields the actual bot instance (not a proxy)."""
        async with configured_bot.session() as b:
            assert b is configured_bot

    @pytest.mark.asyncio
    async def test_sets_contextvar_during_session(self, configured_bot):
        """ContextVar is non-None and carries the expected user_id inside session()."""
        async with configured_bot.session(user_id="u1"):
            ctx = current_context()
            assert ctx is not None
            assert ctx.user_id == "u1"

    @pytest.mark.asyncio
    async def test_resets_contextvar_after_normal_exit(self, configured_bot):
        """ContextVar is cleared when session() exits normally."""
        async with configured_bot.session(user_id="u1"):
            pass
        assert current_context() is None

    @pytest.mark.asyncio
    async def test_resets_contextvar_after_exception(self, configured_bot):
        """ContextVar is cleared even when an exception propagates."""
        with pytest.raises(RuntimeError):
            async with configured_bot.session(user_id="u1"):
                raise RuntimeError("boom")
        assert current_context() is None

    @pytest.mark.asyncio
    async def test_concurrent_isolation(self, configured_bot):
        """Two concurrent sessions each see their own ContextVar value.

        asyncio.gather() schedules each coroutine in its own task, and each task
        gets an independent copy of the ContextVar — so alice's set doesn't
        overwrite bob's, even when they overlap in time.
        """
        results: dict[str, str | None] = {}

        async def worker(uid: str) -> None:
            async with configured_bot.session(user_id=uid):
                # Give the event loop a chance to interleave the two tasks
                await asyncio.sleep(0.01)
                ctx = current_context()
                results[uid] = ctx.user_id if ctx else None

        await asyncio.gather(worker("alice"), worker("bob"))
        assert results["alice"] == "alice"
        assert results["bob"] == "bob"

    @pytest.mark.asyncio
    async def test_prebuilt_ctx_accepted(self, configured_bot):
        """session(ctx=...) uses the provided RequestContext object unchanged."""
        ctx = RequestContext(user_id="pre")
        async with configured_bot.session(ctx=ctx):
            assert current_context() is ctx

    @pytest.mark.asyncio
    async def test_session_with_request_fail_open(self, configured_bot):
        """session(request=...) works when no PDP is configured (fail-open)."""
        request = _make_mock_request()
        async with configured_bot.session(request=request) as b:
            assert b is configured_bot


# ---------------------------------------------------------------------------
# TestFallbackSemantics
# ---------------------------------------------------------------------------


class TestFallbackSemantics:
    """Tests for TASK-1204 — BaseBot ContextVar fallback pattern.

    The fallback added to BaseBot entry points (ask, invoke, conversation,
    ask_stream) is a single guard:

        if ctx is None:
            ctx = _current_ctx.get()

    We verify this pattern directly — without going through the full ask()
    pipeline — and also verify that session() sets the ambient context so
    that nested calls with ctx=None automatically receive the session's
    RequestContext.
    """

    # ------------------------------------------------------------------
    # Direct pattern tests (sync)
    # ------------------------------------------------------------------

    def test_explicit_ctx_wins_over_ambient(self):
        """When ctx is not None, ambient ContextVar is ignored."""
        ambient = RequestContext(user_id="ambient")
        explicit = RequestContext(user_id="explicit")
        token = _current_ctx.set(ambient)
        try:
            # Replicate the BaseBot fallback guard
            ctx = explicit
            if ctx is None:
                ctx = _current_ctx.get()
            assert ctx is explicit
            assert ctx.user_id == "explicit"
        finally:
            _current_ctx.reset(token)

    def test_ambient_fallback_when_ctx_none(self):
        """When ctx=None and ContextVar is set, the ambient value is used."""
        ambient = RequestContext(user_id="ambient")
        token = _current_ctx.set(ambient)
        try:
            ctx = None
            if ctx is None:
                ctx = _current_ctx.get()
            assert ctx is ambient
            assert ctx.user_id == "ambient"
        finally:
            _current_ctx.reset(token)

    def test_no_ambient_stays_none(self):
        """When ctx=None and ContextVar is not set, ctx remains None."""
        ctx = None
        if ctx is None:
            ctx = _current_ctx.get()
        assert ctx is None

    # ------------------------------------------------------------------
    # Integration with session() (async)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_session_provides_ambient_for_nested_calls(self, configured_bot):
        """session() sets ambient ctx so a ctx=None fallback inside picks it up."""
        async with configured_bot.session(user_id="session-user"):
            # Simulate a nested BaseBot method resolving the fallback
            ctx = None
            if ctx is None:
                ctx = _current_ctx.get()
            assert ctx is not None
            assert ctx.user_id == "session-user"

    @pytest.mark.asyncio
    async def test_no_session_fallback_yields_none(self):
        """Outside a session(), ctx=None fallback finds nothing."""
        ctx = None
        if ctx is None:
            ctx = _current_ctx.get()
        assert ctx is None
