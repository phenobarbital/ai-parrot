"""``BotManager._setup_dataplane_guard`` tests (FEAT-598 TASK-3805).

Covers the default data-plane guard wiring: `BotManager.setup()` registers
`_setup_dataplane_guard` as a deferred `on_startup` callback (after
`self.on_startup`, which runs `load_bots`), and that callback injects the
app-level `DataPlanePolicyGuard` into every managed bot that doesn't
already carry its own — never overwriting a bot's pre-set guard, and never
touching any bot when PBAC could not initialize.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from aiohttp import web

from parrot.conf import PARROT_PBAC_POLICY_DIR
from parrot.manager.manager import BotManager


def _manager(bots: dict | None = None) -> BotManager:
    """A `BotManager` with no heavy `__init__` side effects (pattern:
    test_agent_mount_wiring.py) — `_setup_dataplane_guard` only needs
    `self._bots` and `self.logger`.
    """
    bm = BotManager.__new__(BotManager)
    bm._bots = bots if bots is not None else {}
    bm.logger = MagicMock()
    return bm


class TestSetupDataplaneGuardCallback:
    @pytest.mark.asyncio
    async def test_injects_guard_into_bots_without_one(self, monkeypatch):
        """Bots with no `_dataplane_guard` receive the app's guard."""
        guard = object()
        spy = MagicMock(return_value=guard)
        monkeypatch.setattr("parrot.manager.manager.setup_dataplane_guard", spy)

        class _Bot:
            pass

        bot_a = _Bot()
        bot_b = _Bot()
        manager = _manager({"a": bot_a, "b": bot_b})
        app = web.Application()

        await manager._setup_dataplane_guard(app)

        spy.assert_called_once_with(app, policy_dir=PARROT_PBAC_POLICY_DIR)
        assert bot_a._dataplane_guard is guard
        assert bot_b._dataplane_guard is guard

    @pytest.mark.asyncio
    async def test_bot_own_guard_is_never_overwritten(self, monkeypatch):
        """A bot with a pre-set `_dataplane_guard` keeps its own instance."""
        app_guard = object()
        own_guard = object()
        monkeypatch.setattr(
            "parrot.manager.manager.setup_dataplane_guard",
            MagicMock(return_value=app_guard),
        )

        class _Bot:
            pass

        bot_with_own = _Bot()
        bot_with_own._dataplane_guard = own_guard
        bot_without = _Bot()
        manager = _manager({"has-own": bot_with_own, "no-own": bot_without})

        await manager._setup_dataplane_guard(web.Application())

        assert bot_with_own._dataplane_guard is own_guard
        assert bot_without._dataplane_guard is app_guard

    @pytest.mark.asyncio
    async def test_no_guard_available_touches_no_bot(self, monkeypatch):
        """PBAC unavailable (`setup_dataplane_guard` returns None) leaves
        every managed bot untouched — no `_dataplane_guard` attribute is
        set at all, preserving fail-closed 403 behavior downstream.
        """
        monkeypatch.setattr(
            "parrot.manager.manager.setup_dataplane_guard",
            MagicMock(return_value=None),
        )

        class _Bot:
            pass

        bot = _Bot()
        manager = _manager({"only": bot})

        await manager._setup_dataplane_guard(web.Application())

        assert not hasattr(bot, "_dataplane_guard")


class TestSetupRegistersDeferredCallback:
    def test_setup_appends_dataplane_guard_callback_after_load_bots_startup(self):
        """`setup()` must append `_setup_dataplane_guard` to `app.on_startup`
        strictly AFTER `self.on_startup` (which runs `load_bots`) — startup
        callbacks run in append order, so bots are loaded before injection.
        """
        manager = BotManager(enable_registry_bots=False, enable_crews=False)
        app = web.Application()

        manager.setup(app)

        callbacks = list(app.on_startup)
        assert manager.on_startup in callbacks
        assert manager._setup_dataplane_guard in callbacks
        assert callbacks.index(manager.on_startup) < callbacks.index(manager._setup_dataplane_guard)
