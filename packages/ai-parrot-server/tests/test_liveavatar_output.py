"""Unit tests for the server-side LiveAvatar output subscriber wiring (FEAT-243/244)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot.handlers.liveavatar_output import (
    _FanOutSink,
    configure_liveavatar_output_subscriber,
)


def test_registers_startup_and_cleanup_hooks():
    app = web.Application()
    n_start, n_clean = len(app.on_startup), len(app.on_cleanup)

    configure_liveavatar_output_subscriber(app)

    assert len(app.on_startup) == n_start + 1
    assert len(app.on_cleanup) == n_clean + 1


@pytest.mark.asyncio
async def test_start_is_graceful_without_socket_manager():
    """No user_socket_manager -> skip (no task/redis), don't crash startup."""
    app = web.Application()
    configure_liveavatar_output_subscriber(app)
    start_cb = app.on_startup[-1]

    await start_cb(app)

    assert "liveavatar_output_task" not in app
    assert "liveavatar_output_redis" not in app


@pytest.mark.asyncio
async def test_start_launches_subscriber_and_stop_tears_down(monkeypatch):
    """Happy path: background task launched on startup, cancelled + redis closed on stop."""

    class FakeRedis:
        def __init__(self):
            self.closed = False

        async def aclose(self):
            self.closed = True

    fake_redis = FakeRedis()
    monkeypatch.setattr("redis.asyncio.from_url", lambda *a, **k: fake_redis)

    started = asyncio.Event()
    seen = {}

    async def fake_subscriber(redis, socket_manager, *, channel):
        seen["redis"] = redis
        seen["socket_manager"] = socket_manager
        seen["channel"] = channel
        started.set()
        await asyncio.Event().wait()  # run until cancelled

    monkeypatch.setattr(
        "parrot.integrations.liveavatar.output_transport.run_output_subscriber",
        fake_subscriber,
    )

    sm = object()
    app = web.Application()
    app["user_socket_manager"] = sm
    configure_liveavatar_output_subscriber(app, channel="test:chan")
    start_cb, stop_cb = app.on_startup[-1], app.on_cleanup[-1]

    await start_cb(app)
    await asyncio.wait_for(started.wait(), timeout=1)

    # Subscriber wired to the app's socket manager + our channel + redis client.
    assert seen["socket_manager"] is sm
    assert seen["channel"] == "test:chan"
    assert seen["redis"] is fake_redis
    assert app["liveavatar_output_redis"] is fake_redis
    task = app["liveavatar_output_task"]
    assert not task.done()

    await stop_cb(app)

    assert task.cancelled() or task.done()
    assert fake_redis.closed is True
    assert "liveavatar_output_task" not in app
    assert "liveavatar_output_redis" not in app


# ── BotManager.setup gating via ENABLE_LIVEAVATAR_VOICE ──────────────────────


def test_botmanager_skips_subscriber_when_flag_disabled(monkeypatch):
    from types import SimpleNamespace

    import parrot.handlers.liveavatar_output as lo
    from parrot.manager import manager as mgr

    monkeypatch.setattr(mgr, "ENABLE_LIVEAVATAR_VOICE", False)
    called = []
    monkeypatch.setattr(
        lo, "configure_liveavatar_output_subscriber", lambda app: called.append(app)
    )

    mgr.BotManager._setup_liveavatar_voice(SimpleNamespace(app=object()))

    assert called == []


def test_botmanager_wires_subscriber_when_flag_enabled(monkeypatch):
    from types import SimpleNamespace

    import parrot.handlers.liveavatar_output as lo
    from parrot.manager import manager as mgr

    monkeypatch.setattr(mgr, "ENABLE_LIVEAVATAR_VOICE", True)
    called = []
    monkeypatch.setattr(
        lo, "configure_liveavatar_output_subscriber", lambda app: called.append(app)
    )

    app = object()
    mgr.BotManager._setup_liveavatar_voice(SimpleNamespace(app=app))

    assert called == [app]


# ── _FanOutSink unit tests (FEAT-244 TASK-1586) ──────────────────────────────


@pytest.mark.asyncio
async def test_fanout_delivers_to_both():
    """Fan-out sink forwards to both managers when both are present."""
    a = MagicMock()
    a.broadcast_to_channel = AsyncMock()
    b = MagicMock()
    b.broadcast_to_channel = AsyncMock()

    sink = _FanOutSink([a, b])
    await sink.broadcast_to_channel("sess-1", {"type": "data"})

    a.broadcast_to_channel.assert_awaited_once_with("sess-1", {"type": "data"})
    b.broadcast_to_channel.assert_awaited_once_with("sess-1", {"type": "data"})


@pytest.mark.asyncio
async def test_fanout_skips_none_and_survives_failure():
    """Fan-out sink ignores None entries and continues when one manager raises."""
    good = MagicMock()
    good.broadcast_to_channel = AsyncMock()
    bad = MagicMock()
    bad.broadcast_to_channel = AsyncMock(side_effect=RuntimeError("boom"))

    # None in the list is silently dropped; bad raises but good still runs.
    sink = _FanOutSink([None, bad, good])
    await sink.broadcast_to_channel("sess-1", {"type": "data"})  # must not raise

    good.broadcast_to_channel.assert_awaited_once()


@pytest.mark.asyncio
async def test_fanout_only_user_socket_manager():
    """Fan-out with only user_socket_manager behaves like the pre-FEAT-244 path."""
    sm = MagicMock()
    sm.broadcast_to_channel = AsyncMock()

    sink = _FanOutSink([sm, None])
    await sink.broadcast_to_channel("sess-1", {"x": 1})

    sm.broadcast_to_channel.assert_awaited_once_with("sess-1", {"x": 1})


@pytest.mark.asyncio
async def test_fanout_only_stream_handler():
    """Fan-out with only stream_handler delivers when user_socket_manager is absent."""
    sh = MagicMock()
    sh.broadcast_to_channel = AsyncMock()

    sink = _FanOutSink([None, sh])
    await sink.broadcast_to_channel("sess-1", {"y": 2})

    sh.broadcast_to_channel.assert_awaited_once_with("sess-1", {"y": 2})
