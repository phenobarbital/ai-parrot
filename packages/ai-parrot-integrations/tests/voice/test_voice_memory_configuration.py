"""FEAT-886 — voice sessions get cross-turn memory under the new ``memory_type='auto'`` default."""
from __future__ import annotations

import logging

from parrot.voice.handler import configure_voice_memory


class _Bot:
    def __init__(self, memory_type="auto", fail_redis=False):
        self.memory_type = memory_type
        self.conversation_memory = None
        self.configured_as = []
        self._fail_redis = fail_redis

    def configure_conversation_memory(self):
        self.configured_as.append(self.memory_type)
        if self.memory_type == "redis" and self._fail_redis:
            raise ConnectionError("redis down")
        self.conversation_memory = object()


def test_auto_default_becomes_redis():
    for default in ("auto", "memory", None, ""):
        bot = _Bot(default)
        configure_voice_memory(bot, logging.getLogger("t"), "s1")
        assert bot.configured_as == ["redis"] and bot.conversation_memory is not None


def test_explicit_file_is_kept_and_existing_memory_is_untouched():
    bot = _Bot("file")
    configure_voice_memory(bot, logging.getLogger("t"), "s1")
    assert bot.configured_as == ["file"]
    again = _Bot("auto")
    again.conversation_memory = "existing"
    configure_voice_memory(again, logging.getLogger("t"), "s1")
    assert again.configured_as == [] and again.conversation_memory == "existing"


def test_redis_failure_falls_back_to_in_memory_explicitly():
    bot = _Bot("auto", fail_redis=True)
    configure_voice_memory(bot, logging.getLogger("t"), "s1")
    assert bot.configured_as == ["redis", "memory"] and bot.conversation_memory is not None
