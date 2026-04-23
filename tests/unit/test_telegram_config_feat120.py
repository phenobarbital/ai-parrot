"""Unit tests for FEAT-120 TelegramAgentConfig additions.

Tests verify that max_document_size_mb and enable_reply_context fields
are present with correct defaults and accept custom values.
"""
import pytest
from parrot.integrations.telegram.models import TelegramAgentConfig


class TestTelegramConfigFeat120:
    """Tests for FEAT-120 config fields on TelegramAgentConfig."""

    def test_max_document_size_mb_default(self):
        """Default max_document_size_mb is 20."""
        config = TelegramAgentConfig(name="test", chatbot_id="bot1")
        assert config.max_document_size_mb == 20

    def test_max_document_size_mb_custom(self):
        """Custom max_document_size_mb is accepted."""
        config = TelegramAgentConfig(name="test", chatbot_id="bot1", max_document_size_mb=50)
        assert config.max_document_size_mb == 50

    def test_max_document_size_mb_zero_allowed(self):
        """max_document_size_mb of 0 disables documents effectively."""
        config = TelegramAgentConfig(name="test", chatbot_id="bot1", max_document_size_mb=0)
        assert config.max_document_size_mb == 0

    def test_enable_reply_context_default(self):
        """Default enable_reply_context is True."""
        config = TelegramAgentConfig(name="test", chatbot_id="bot1")
        assert config.enable_reply_context is True

    def test_enable_reply_context_disabled(self):
        """enable_reply_context can be disabled."""
        config = TelegramAgentConfig(name="test", chatbot_id="bot1", enable_reply_context=False)
        assert config.enable_reply_context is False

    def test_existing_fields_unaffected(self):
        """New fields don't break existing TelegramAgentConfig fields."""
        config = TelegramAgentConfig(
            name="test",
            chatbot_id="bot1",
            singleton_agent=False,
        )
        assert config.singleton_agent is False
        assert config.max_document_size_mb == 20
        assert config.enable_reply_context is True

    def test_both_fields_custom(self):
        """Both new fields can be set together."""
        config = TelegramAgentConfig(
            name="test",
            chatbot_id="bot1",
            max_document_size_mb=100,
            enable_reply_context=False,
        )
        assert config.max_document_size_mb == 100
        assert config.enable_reply_context is False
