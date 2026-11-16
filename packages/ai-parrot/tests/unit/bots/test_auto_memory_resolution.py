"""FEAT-886 M12 — memory_type='auto' resolution and no-fallback when Redis was selected."""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

import parrot.conf as parrot_conf
from parrot.bots import abstract as bots_abstract
from parrot.bots.base import BaseBot
from parrot.clients.base import AbstractClient
from parrot.memory import FileConversationMemory, InMemoryConversation, RedisConversation
from parrot.models import AIMessage


class _StubClient(AbstractClient):
    client_type = "stub-auto"
    supported_models = ["stub"]

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("model", "stub")
        super().__init__(**kwargs)

    async def get_client(self) -> "_StubClient":
        return self

    async def _ensure_client(self) -> "_StubClient":
        return self

    async def ask(self, prompt: str, model: Optional[str] = None, **kwargs: Any) -> AIMessage:
        raise NotImplementedError

    async def ask_stream(self, prompt: str, **kwargs: Any):
        raise NotImplementedError
        yield  # pragma: no cover

    async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]):
        raise NotImplementedError

    async def invoke(self, prompt: str, **kwargs: Any):
        raise NotImplementedError


def _bot(**kw: Any) -> BaseBot:
    return BaseBot(name="auto-mem-probe", llm=_StubClient(), injection_detection=False, **kw)


class _Boom:
    def __init__(self, *a: Any, **kw: Any) -> None:
        raise ConnectionError("down")


def test_auto_memory_resolution(monkeypatch):
    """Synthesized defaults -> in-memory (no Redis I/O); explicit URL / injected redis_url -> Redis; explicit types win."""
    assert _bot().memory_type == "auto"
    monkeypatch.setattr(bots_abstract, "REDIS_HISTORY_EXPLICIT", False)
    bot = _bot()

    class _NoRedis:
        def __init__(self, *a: Any, **kw: Any) -> None:
            raise AssertionError("Redis must not be constructed")

    with monkeypatch.context() as m:
        m.setattr(bots_abstract, "RedisConversation", _NoRedis)
        assert isinstance(bot.get_conversation_memory("auto"), InMemoryConversation)
        # Redis-only keys must not crash the in-memory branch
        assert isinstance(bot.get_conversation_memory("auto", key_prefix="x", history_ttl=5), InMemoryConversation)
    # (3) host-injected URL
    mem = bot.get_conversation_memory("auto", redis_url="redis://localhost:6379/9")
    assert isinstance(mem, RedisConversation) and "6379/9" in str(mem.redis_url)
    # (4) explicit redis wins with EXPLICIT False
    assert isinstance(bot.get_conversation_memory("redis"), RedisConversation)
    # (2) EXPLICIT True
    monkeypatch.setattr(bots_abstract, "REDIS_HISTORY_EXPLICIT", True)
    assert isinstance(bot.get_conversation_memory("auto"), RedisConversation)
    assert isinstance(bot.get_conversation_memory("memory"), InMemoryConversation)
    assert isinstance(bot.get_conversation_memory("file"), FileConversationMemory)
    with pytest.raises(ValueError):
        bot.get_conversation_memory("bogus")


def test_auto_redis_failure_surfaces(monkeypatch):
    """A configured Redis failure raises from configure_conversation_memory; no in-memory fallback."""
    monkeypatch.setattr(bots_abstract, "RedisConversation", _Boom)
    monkeypatch.setattr(bots_abstract, "REDIS_HISTORY_EXPLICIT", False)

    bot = _bot(memory_type="redis")
    with pytest.raises(ConnectionError):
        bot.configure_conversation_memory()
    assert bot.conversation_memory is None

    bot = _bot(memory_type="auto", memory_config={"redis_url": "redis://x:1/0"})
    with pytest.raises(ConnectionError):
        bot.configure_conversation_memory()

    monkeypatch.setattr(bots_abstract, "REDIS_HISTORY_EXPLICIT", True)
    with pytest.raises(ConnectionError):
        _bot(memory_type="auto").configure_conversation_memory()

    monkeypatch.setattr(bots_abstract, "REDIS_HISTORY_EXPLICIT", False)
    bot = _bot(memory_type="auto")
    bot.configure_conversation_memory()
    assert isinstance(bot.conversation_memory, InMemoryConversation)

    monkeypatch.setattr(bots_abstract, "FileConversationMemory", _Boom)
    bot = _bot(memory_type="file")
    bot.configure_conversation_memory()
    assert isinstance(bot.conversation_memory, InMemoryConversation)


def test_redis_history_url_is_operator_value_when_explicit(monkeypatch):
    """EXPLICIT True -> REDIS_HISTORY_URL == the operator's value; otherwise the synthesized host/port URL."""
    real_get = parrot_conf.config.get
    try:
        monkeypatch.setattr(
            parrot_conf.config, "get",
            lambda key, *a, **kw: "redis://ops:6380/7" if key == "REDIS_HISTORY_URL" else real_get(key, *a, **kw),
        )
        importlib.reload(parrot_conf)
        assert parrot_conf.REDIS_HISTORY_EXPLICIT is True
        assert parrot_conf.REDIS_HISTORY_URL == "redis://ops:6380/7"
        monkeypatch.setattr(
            parrot_conf.config, "get",
            lambda key, *a, **kw: "  " if key == "REDIS_HISTORY_URL" else real_get(key, *a, **kw),
        )
        importlib.reload(parrot_conf)
        assert parrot_conf.REDIS_HISTORY_EXPLICIT is False
        assert parrot_conf.REDIS_HISTORY_URL.startswith(f"redis://{parrot_conf.REDIS_HOST}")
    finally:
        monkeypatch.undo()
        importlib.reload(parrot_conf)


def test_voicebot_auto_means_redis():
    """The VoiceBot normalisation treats 'auto' like the old default; 'file' is kept (source-level pin)."""
    src = (Path(bots_abstract.__file__).parent / "voice.py").read_text(encoding="utf-8")
    assert 'self.memory_type in ("memory", "auto")' in src
    assert 'self.memory_type == "memory"' not in src


def test_bot_model_validation_accepts_auto():
    """BotModel memory_type='auto' validates; an unknown value still raises ValueError."""
    from parrot.models.bots import BotModel

    assert BotModel(name="x", memory_type="auto").memory_type == "auto"
    with pytest.raises(ValueError):
        BotModel(name="x", memory_type="bogus")
