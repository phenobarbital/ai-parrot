"""IntegrationBotManager.shutdown() releases MS Teams wrapper resources (TASK-4059)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.manager import IntegrationBotManager  # verified: manager.py:91


def _manager() -> IntegrationBotManager:
    bot_manager = MagicMock()
    bot_manager.get_app = MagicMock(return_value=MagicMock())
    return IntegrationBotManager(bot_manager=bot_manager)


def _fake_msteams_wrapper() -> MagicMock:
    wrapper = MagicMock()
    wrapper.close_formdesigner_client = AsyncMock()
    wrapper.close_voice_transcriber = AsyncMock()
    return wrapper


@pytest.mark.asyncio
async def test_shutdown_closes_msteams_wrapper_resources():
    """Both close methods are awaited on every MS Teams wrapper, then the registry is cleared."""
    manager = _manager()
    wrappers = [_fake_msteams_wrapper(), _fake_msteams_wrapper()]
    manager.msteams_bots["a"] = wrappers[0]
    manager.msteams_bots["b"] = wrappers[1]

    await manager.shutdown()

    for wrapper in wrappers:
        wrapper.close_formdesigner_client.assert_awaited_once()
        wrapper.close_voice_transcriber.assert_awaited_once()
    assert manager.msteams_bots == {}


@pytest.mark.asyncio
async def test_shutdown_msteams_close_failure_is_isolated():
    """A failing close is logged and neither skips the sibling close nor other wrappers."""
    manager = _manager()
    failing = _fake_msteams_wrapper()
    failing.close_formdesigner_client.side_effect = RuntimeError("boom")
    healthy = _fake_msteams_wrapper()
    manager.msteams_bots["failing"] = failing
    manager.msteams_bots["healthy"] = healthy

    await manager.shutdown()

    failing.close_voice_transcriber.assert_awaited_once()
    healthy.close_formdesigner_client.assert_awaited_once()
    healthy.close_voice_transcriber.assert_awaited_once()
    assert manager.msteams_bots == {}
