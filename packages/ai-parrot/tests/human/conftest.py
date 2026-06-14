"""Shared pytest fixtures for parrot.human tests."""
from __future__ import annotations

import sys
import types

import pytest


@pytest.fixture
def notify_log(monkeypatch):
    """Install a fake ``notify`` module and return the captured-send log.

    The log is a list of dicts; each dict has at minimum:
    - ``provider``: the provider name passed to ``Notify(provider, ...)``
    - ``opts``: the kwargs passed to ``Notify(provider, **opts)``
    - all kwargs forwarded to ``conn.send(**kwargs)``
      (e.g. ``recipient``, ``message``, ``subject``, ``cc``)
    """
    log: list = []

    class _Conn:
        def __init__(self, provider: str, opts: dict) -> None:
            self.provider = provider
            self.opts = opts

        async def __aenter__(self) -> "_Conn":
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

        async def send(self, **kwargs: object) -> list:
            log.append({"provider": self.provider, "opts": self.opts, **kwargs})
            return [types.SimpleNamespace(message_id="fake-1")]

    def _notify(provider: str, **opts: object) -> _Conn:
        return _Conn(provider, opts)

    notify_mod = types.ModuleType("notify")
    notify_mod.Notify = _notify
    models_mod = types.ModuleType("notify.models")

    class Actor:
        def __init__(self, name: str | None = None, account: dict | None = None) -> None:
            self.name = name
            self.account = account or {}

    class Chat:
        def __init__(self, chat_id: str | None = None) -> None:
            self.chat_id = chat_id

    class Channel:
        def __init__(self, channel_id: str | None = None) -> None:
            self.channel_id = channel_id

    models_mod.Actor = Actor
    models_mod.Chat = Chat
    models_mod.Channel = Channel
    notify_mod.models = models_mod

    monkeypatch.setitem(sys.modules, "notify", notify_mod)
    monkeypatch.setitem(sys.modules, "notify.models", models_mod)
    return log
