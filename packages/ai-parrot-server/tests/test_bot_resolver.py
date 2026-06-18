"""Unit tests for the BotManager-backed LiveAvatar bot resolver (FEAT-243)."""

from types import SimpleNamespace

import pytest

from parrot.manager import bot_resolver as br
from parrot.manager.bot_resolver import (
    botmanager_bot_resolver,
    build_standalone_bot_resolver,
)


class FakeManager:
    def __init__(self, bots):
        self._bots = bots
        self.calls = []

    async def get_bot(self, name, request=None, **kwargs):
        self.calls.append((name, request))
        return self._bots.get(name)


@pytest.mark.asyncio
async def test_resolver_returns_bot_by_name():
    bot = SimpleNamespace(name="demo")
    resolver = botmanager_bot_resolver(FakeManager({"demo": bot}))

    resolved = await resolver("demo")

    assert resolved is bot


@pytest.mark.asyncio
async def test_resolver_passes_request_none_for_programmatic_use():
    manager = FakeManager({"demo": object()})
    resolver = botmanager_bot_resolver(manager)

    await resolver("demo")

    assert manager.calls == [("demo", None)]  # request=None -> no PBAC


@pytest.mark.asyncio
async def test_resolver_raises_keyerror_for_unknown_agent():
    resolver = botmanager_bot_resolver(FakeManager({}))

    with pytest.raises(KeyError, match="unknown agent"):
        await resolver("nope")


def test_build_standalone_resolver_uses_safe_botmanager_flags(monkeypatch):
    """Standalone resolver builds a BotManager with no DB / crews / swagger."""
    captured = {}

    class FakeBotManager:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def get_bot(self, name, request=None, **kwargs):  # pragma: no cover
            return None

    monkeypatch.setattr(br, "BotManager", FakeBotManager)

    resolver = build_standalone_bot_resolver()

    assert callable(resolver)
    assert captured == {
        "enable_database_bots": False,
        "enable_registry_bots": True,
        "enable_crews": False,
        "enable_swagger_api": False,
    }
