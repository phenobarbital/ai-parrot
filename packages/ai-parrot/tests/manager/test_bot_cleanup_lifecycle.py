"""Tests for BotManager cleanup lifecycle — FEAT-114 bot-cleanup-lifecycle.

Covers:
- Unit tests for _cleanup_all_bots and _safe_cleanup behaviour.
- Registration order of on_cleanup callbacks.
- BOT_CLEANUP_TIMEOUT conf constant (default and env-override).
- Integration: aiohttp on_cleanup signal triggers bot.cleanup().
- Integration: HookableAgent-style bot stops hooks then runs resource cleanup.
"""

import asyncio
import importlib
from unittest.mock import patch

import pytest
from aiohttp import web

from parrot.manager.manager import BotManager


# ---------------------------------------------------------------------------
# Duck-typed bot stub
# ---------------------------------------------------------------------------

class _DummyBot:
    """Duck-typed stand-in for AbstractBot used in cleanup tests.

    BotManager only reads ``.name`` and awaits ``.cleanup()`` during
    _cleanup_all_bots, so this minimal stub is sufficient.
    """

    def __init__(
        self,
        name: str,
        *,
        raises: bool = False,
        hangs: bool = False,
    ) -> None:
        self.name = name
        self.cleaned = False
        self._raises = raises
        self._hangs = hangs

    async def cleanup(self) -> None:
        if self._hangs:
            await asyncio.sleep(10)  # much longer than any test timeout
        if self._raises:
            raise RuntimeError(f"{self.name} blew up during cleanup")
        self.cleaned = True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def manager() -> BotManager:
    """Minimal BotManager with all optional subsystems disabled."""
    return BotManager(
        enable_database_bots=False,
        enable_crews=False,
        enable_registry_bots=False,
        enable_swagger_api=False,
    )


@pytest.fixture
def app_with_manager(manager: BotManager) -> tuple[web.Application, BotManager]:
    """aiohttp Application wired with BotManager.setup().

    ``_register_shared_redis`` is patched out to avoid real Redis connections
    while still inserting a dummy ``_cleanup_shared_redis`` callback so that
    the ordering assertion in test_cleanup_registered_on_app can verify the
    contract.
    """
    app = web.Application()

    async def _noop_shared_redis(a: web.Application) -> None:
        pass

    _noop_shared_redis.__name__ = "_cleanup_shared_redis"

    def _fake_register_redis(self_: BotManager) -> None:
        # Simulate the real registration so ordering tests work.
        self_.app.on_cleanup.append(_noop_shared_redis)

    with patch.object(BotManager, "_register_shared_redis", _fake_register_redis):
        manager.setup(app)

    return app, manager


# ---------------------------------------------------------------------------
# Unit tests — _cleanup_all_bots
# ---------------------------------------------------------------------------

async def test_cleanup_all_bots_empty(manager: BotManager) -> None:
    """With no bots registered, _cleanup_all_bots must log and return."""
    app = web.Application()
    # Must complete without error and without side-effects.
    await manager._cleanup_all_bots(app)


async def test_cleanup_all_bots_happy_path(manager: BotManager) -> None:
    """Two bots: both cleanup() coroutines must be awaited exactly once."""
    a, b = _DummyBot("a"), _DummyBot("b")
    manager._bots = {"a": a, "b": b}

    await manager._cleanup_all_bots(web.Application())

    assert a.cleaned is True
    assert b.cleaned is True
    assert manager._cleaned_up == {"a", "b"}


async def test_cleanup_all_bots_isolates_exceptions(manager: BotManager) -> None:
    """One bot raising must NOT prevent the other bot from completing."""
    bad, good = _DummyBot("bad", raises=True), _DummyBot("good")
    manager._bots = {"bad": bad, "good": good}

    await manager._cleanup_all_bots(web.Application())

    assert good.cleaned is True
    assert "good" in manager._cleaned_up
    assert "bad" not in manager._cleaned_up


async def test_cleanup_all_bots_timeout(
    manager: BotManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hanging bot must be cancelled; other bots still complete."""
    monkeypatch.setattr("parrot.manager.manager.BOT_CLEANUP_TIMEOUT", 0.05)

    hanger, normal = _DummyBot("hang", hangs=True), _DummyBot("ok")
    manager._bots = {"hang": hanger, "ok": normal}

    await manager._cleanup_all_bots(web.Application())

    assert normal.cleaned is True
    assert "ok" in manager._cleaned_up
    assert "hang" not in manager._cleaned_up


async def test_cleanup_registered_on_app(
    app_with_manager: tuple[web.Application, BotManager],
) -> None:
    """setup() must append _cleanup_all_bots BEFORE _cleanup_shared_redis."""
    app, _ = app_with_manager
    names = [cb.__name__ for cb in app.on_cleanup]
    assert "_cleanup_all_bots" in names, "_cleanup_all_bots not registered"
    assert "_cleanup_shared_redis" in names, "_cleanup_shared_redis not registered"
    assert names.index("_cleanup_all_bots") < names.index("_cleanup_shared_redis")


# ---------------------------------------------------------------------------
# Conf constant tests
# ---------------------------------------------------------------------------

def test_bot_cleanup_timeout_default() -> None:
    """Default fallback declared in conf.py is 20 seconds."""
    from parrot.conf import BOT_CLEANUP_TIMEOUT
    assert BOT_CLEANUP_TIMEOUT == 20


def test_bot_cleanup_timeout_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """With BOT_CLEANUP_TIMEOUT=5 in env the constant reads 5 on reload."""
    monkeypatch.setenv("BOT_CLEANUP_TIMEOUT", "5")
    import parrot.conf as parrot_conf
    importlib.reload(parrot_conf)
    try:
        assert parrot_conf.BOT_CLEANUP_TIMEOUT == 5
    finally:
        # Restore defaults so downstream tests see 20.
        monkeypatch.delenv("BOT_CLEANUP_TIMEOUT", raising=False)
        importlib.reload(parrot_conf)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

async def test_aiohttp_cleanup_triggers_bot_cleanup(
    app_with_manager: tuple[web.Application, BotManager],
) -> None:
    """Running app.on_cleanup callbacks must invoke bot.cleanup() on all bots."""
    app, manager = app_with_manager
    a, b = _DummyBot("a"), _DummyBot("b")
    manager._bots = {"a": a, "b": b}

    for cb in list(app.on_cleanup):
        await cb(app)

    assert a.cleaned is True
    assert b.cleaned is True


async def test_hookable_cleanup_via_botmanager_end_to_end(
    app_with_manager: tuple[web.Application, BotManager],
) -> None:
    """A HookableAgent-style bot must stop hooks THEN run resource cleanup."""

    class _HookableRecorder:
        """Minimal recorder that mimics HookableAgent.cleanup() order."""

        def __init__(self) -> None:
            self.name = "hookable"
            self.order: list[str] = []

        async def cleanup(self) -> None:
            self.order.append("stop_hooks")
            self.order.append("super_cleanup")

    app, manager = app_with_manager
    bot = _HookableRecorder()
    manager._bots = {bot.name: bot}

    for cb in list(app.on_cleanup):
        await cb(app)

    assert bot.order == ["stop_hooks", "super_cleanup"]
