"""FEAT-621 R2 guards (AC9, AC18): Studio ids never resolve through the legacy BotManager paths."""
import asyncio
import logging
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from parrot.handlers.studio.storage.models import STUDIO_KEY_PREFIX, STUDIO_TOOLING_REF_PREFIX
from parrot.manager import manager as manager_module
from parrot.manager.manager import BotManager, cleanup_bot_instance


def _manager() -> BotManager:
    return BotManager(enable_database_bots=False, enable_crews=False, enable_registry_bots=True,
                      enable_swagger_api=False)


def test_prefixes_match_models():
    assert manager_module._STUDIO_PREFIXES == (STUDIO_KEY_PREFIX, STUDIO_TOOLING_REF_PREFIX)


@pytest.mark.parametrize("name", ["studio:acme:sales", "studio:-:x_ab12", f"studio-agent:{uuid4()}"])
@pytest.mark.parametrize("new", [False, True])
async def test_get_bot_refuses_studio_prefixes(name, new):
    manager = _manager()
    legacy = Mock()
    legacy.name = name                                   # even a (forced) entry under that exact name is not served
    manager._bots[name] = legacy
    manager._botdef[name] = Mock
    before = (dict(manager._bots), dict(manager._botdef))
    assert await manager.get_bot(name, new=new, session_id="s1") is None
    assert (manager._bots, manager._botdef) == before


async def test_get_bot_still_resolves_legacy_names():
    manager = _manager()
    bot = Mock()
    bot.name = "legacy-agent"
    manager._bots["legacy-agent"] = bot
    assert await manager.get_bot("legacy-agent") is bot
    bot2 = Mock()
    bot2.name = "studio-helper"
    manager._bots["studio-helper"] = bot2
    assert await manager.get_bot("studio-helper") is bot2


def test_add_bot_refuses_studio_instance():
    manager = _manager()
    studio_bot = Mock()
    studio_bot.name = "a1"
    studio_bot._studio_key = "studio:acme:a1"
    with pytest.raises(ValueError):
        manager.add_bot(studio_bot)
    assert "a1" not in manager._bots and "a1" not in manager._botdef
    plain = Mock(spec=["name"])
    plain.name = "plain"
    manager.add_bot(plain)
    assert manager._bots["plain"] is plain


async def test_cleanup_bot_instance_isolation(monkeypatch, caplog):
    ok = Mock()
    ok.cleanup = AsyncMock()
    assert await cleanup_bot_instance(ok, label="ok") is True and ok.cleanup.await_count == 1
    boom = Mock()
    boom.cleanup = AsyncMock(side_effect=RuntimeError("boom"))
    with caplog.at_level(logging.WARNING, logger="Parrot.Manager"):
        assert await cleanup_bot_instance(boom, label="boom") is False
    assert "boom" in caplog.text
    monkeypatch.setattr(manager_module, "BOT_CLEANUP_TIMEOUT", 0.01)
    slow = Mock()

    async def _hang():
        await asyncio.sleep(5)

    slow.cleanup = _hang
    assert await cleanup_bot_instance(slow, label="slow") is False


async def test_safe_cleanup_keeps_its_name_guard():
    manager = _manager()
    bot = Mock()
    bot.cleanup = AsyncMock()
    assert await manager._safe_cleanup("b1", bot) is True
    assert await manager._safe_cleanup("b1", bot) is True
    assert bot.cleanup.await_count == 1                                   # second call hit the guard
    failing = Mock()
    failing.cleanup = AsyncMock(side_effect=RuntimeError("x"))
    assert await manager._safe_cleanup("b2", failing) is False
    assert await manager._safe_cleanup("b2", failing) is False            # not recorded: retried
    assert failing.cleanup.await_count == 2
