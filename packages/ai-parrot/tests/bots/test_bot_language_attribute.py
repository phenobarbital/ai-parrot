"""Tests for the bot-level `language` attribute (FEAT-638 TASK-4119)."""

from unittest.mock import MagicMock, patch

import pytest

from parrot.bots.basic import BasicBot
from parrot.bots.chatbot import Chatbot


def _patched(cls, **kwargs):
    """Construct a bot without loading the real pytector model."""
    with patch("parrot.bots.guardrails.builtin.prompt_injection._get_shared_injection_detector") as m:
        m.return_value = MagicMock(detect_injection=MagicMock(return_value=(False, 0.0)))
        return cls(name="TestBot", **kwargs)


def _patched_bot(**kwargs):
    return _patched(BasicBot, **kwargs)


def test_language_defaults_to_none():
    assert _patched_bot().language is None


def test_language_kwarg_is_stored_raw():
    assert _patched_bot(language="es-MX").language == "es-MX"  # raw, not normalized


def test_language_class_attribute_is_honored():
    class SpanishBot(BasicBot):
        language = "es"

    assert _patched(SpanishBot).language == "es"
    assert _patched(SpanishBot, language="en").language == "en"


@pytest.mark.asyncio
async def test_chatbot_manual_config_keeps_none():
    """Chatbot.from_manual_config no longer forces "en" (hard cut)."""
    bot = Chatbot.__new__(Chatbot)
    bot.logger = MagicMock()
    bot.name = "T"
    bot.enable_tools = False
    bot.tool_manager = MagicMock()
    bot._initial_embedding_model = MagicMock(return_value={})
    await bot.from_manual_config()
    assert bot.language is None


def test_chatbot_from_db_language_default_is_none():
    bot = Chatbot.__new__(Chatbot)
    assert bot._from_db(MagicMock(spec=[]), "language", default=None) is None
    row = MagicMock()
    row.language = ""
    assert bot._from_db(row, "language", default=None) is None
