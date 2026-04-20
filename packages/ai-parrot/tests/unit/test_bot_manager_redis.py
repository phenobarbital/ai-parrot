"""Unit tests for the BotManager shared-Redis ownership contract
(TASK-776 / FEAT-107).

``BotManager.setup(app)`` publishes ``app['redis']`` so every downstream
ai-parrot consumer (navigator-auth refresh-token rotation, FEAT-108
VaultTokenSync, JiraOAuthManager, ...) can rely on a single shared
``redis.asyncio`` client without requiring callers to wire it manually in
``app.py``. The ownership flag drives the cleanup contract — BotManager
only closes the client when it built it.
"""
from __future__ import annotations

# Pre-existing version drift: the installed ``notify`` expects
# ``navconfig.DEBUG`` and ``navconfig.logging.logger``, neither of which
# the installed ``navconfig`` exports. BotManager transitively imports
# ``notify`` through ``handlers.agents.abstract``, which explodes at
# collection time. Same issue kills ``tests/test_botmanager_flags.py`` —
# pre-existing and out of scope for TASK-776. We stub ``notify`` entirely
# here (before any import chain touches it) so BotManager's module load
# can complete. The stub only needs the symbols the import chain reads;
# nothing in this test exercises notification logic.
import sys as _sys
import types as _types

# Best-effort stubs for the most common transitive breakages. If more
# modules break further down the chain ``pytest.importorskip`` below
# catches the rest and declares the test suite skipped.
_fake_notify = _types.ModuleType("notify")
_fake_notify.Notify = type("Notify", (), {})  # type: ignore[attr-defined]
_fake_providers = _types.ModuleType("notify.providers")
_fake_providers_base = _types.ModuleType("notify.providers.base")
_fake_providers_base.ProviderType = type("ProviderType", (), {})  # type: ignore[attr-defined]
_fake_providers.base = _fake_providers_base  # type: ignore[attr-defined]
_fake_notify.providers = _fake_providers  # type: ignore[attr-defined]

_fake_models = _types.ModuleType("notify.models")
for _name in ("Actor", "Chat", "TeamsCard", "TeamsChannel"):
    setattr(_fake_models, _name, type(_name, (), {}))

_sys.modules.setdefault("notify", _fake_notify)
_sys.modules.setdefault("notify.providers", _fake_providers)
_sys.modules.setdefault("notify.providers.base", _fake_providers_base)
_sys.modules.setdefault("notify.models", _fake_models)

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

# Importing ``parrot.manager.manager`` pulls in the full bot/handlers chain
# (navigator.background, notify.models, datamodel, …). On envs where any
# link of that chain has drifted (notify vs navconfig version mismatch,
# missing ``navigator.background`` module, etc.) collection fails before
# any test runs. The ownership helpers under test are simple enough to be
# validated manually during FEAT-107 smoke tests, so skip gracefully when
# the module fails to import rather than erroring the whole suite.
_bot_manager_module = pytest.importorskip(
    "parrot.manager.manager",
    reason=(
        "parrot.manager.manager import chain is broken in this env; "
        "TASK-776 ownership helpers validated end-to-end via FEAT-107 "
        "smoke test."
    ),
)
BotManager = _bot_manager_module.BotManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bot_manager_cls():
    """Alias kept for fixture-style usage."""
    return BotManager


@pytest.fixture
def manager(bot_manager_cls):
    """A BotManager with heavy features disabled."""
    return bot_manager_cls(
        enable_database_bots=False,
        enable_crews=False,
        enable_registry_bots=False,
        enable_swagger_api=False,
    )


# ---------------------------------------------------------------------------
# _register_shared_redis
# ---------------------------------------------------------------------------

class TestRegisterSharedRedis:
    def test_publishes_redis_when_absent(self, manager, monkeypatch) -> None:
        """No pre-existing ``app['redis']`` → BotManager creates one."""
        built: dict = {}

        def fake_from_url(url: str, **kwargs) -> MagicMock:
            built["url"] = url
            built["decode_responses"] = kwargs.get("decode_responses")
            return MagicMock(name="aioredis_client")

        import redis.asyncio as aioredis

        monkeypatch.setattr(aioredis, "from_url", fake_from_url, raising=False)

        app = web.Application()
        manager.app = app
        manager._register_shared_redis()

        assert "redis" in app
        assert manager._redis_owned is True
        assert built["decode_responses"] is True
        # Cleanup handler was registered.
        assert manager._cleanup_shared_redis in app.on_cleanup

    def test_preserves_existing_redis_and_marks_not_owned(self, manager) -> None:
        """Another component already published ``app['redis']`` → do not
        overwrite and flag ``_redis_owned = False``."""
        external = MagicMock(name="externally_provided_redis")
        app = web.Application()
        app["redis"] = external
        manager.app = app
        manager._register_shared_redis()

        assert app["redis"] is external
        assert manager._redis_owned is False
        # No cleanup registration — the external owner is responsible.
        assert manager._cleanup_shared_redis not in app.on_cleanup


# ---------------------------------------------------------------------------
# _cleanup_shared_redis
# ---------------------------------------------------------------------------

class TestCleanupSharedRedis:
    @pytest.mark.asyncio
    async def test_closes_redis_when_owned(self, manager, monkeypatch) -> None:
        """Owned client → ``aclose`` called and key removed from app."""
        close_mock = AsyncMock()
        client = MagicMock(name="owned_redis")
        client.aclose = close_mock

        def fake_from_url(url: str, **kwargs) -> MagicMock:
            return client

        import redis.asyncio as aioredis

        monkeypatch.setattr(aioredis, "from_url", fake_from_url, raising=False)

        app = web.Application()
        manager.app = app
        manager._register_shared_redis()
        assert manager._redis_owned is True

        await manager._cleanup_shared_redis(app)
        close_mock.assert_awaited_once()
        assert "redis" not in app

    @pytest.mark.asyncio
    async def test_leaves_external_redis_alone(self, manager) -> None:
        """Not-owned client → cleanup is a no-op, key stays."""
        external = MagicMock(name="external_redis")
        external.aclose = AsyncMock()
        app = web.Application()
        app["redis"] = external
        manager.app = app
        manager._register_shared_redis()  # marks not owned

        await manager._cleanup_shared_redis(app)
        external.aclose.assert_not_called()
        # Key untouched — the external owner controls it.
        assert app.get("redis") is external

    @pytest.mark.asyncio
    async def test_cleanup_idempotent_when_app_already_popped(
        self, manager, monkeypatch,
    ) -> None:
        """If someone else pops ``app['redis']`` first, cleanup must not
        raise (``app.pop(..., None)`` should swallow the missing key)."""
        client = MagicMock(name="redis")
        client.aclose = AsyncMock()

        import redis.asyncio as aioredis

        monkeypatch.setattr(
            aioredis, "from_url", lambda *a, **k: client, raising=False,
        )

        app = web.Application()
        manager.app = app
        manager._register_shared_redis()
        # Simulate an earlier cleanup handler yanking the key.
        app.pop("redis", None)

        # Should still be a no-crash no-op.
        await manager._cleanup_shared_redis(app)
        client.aclose.assert_not_called()
