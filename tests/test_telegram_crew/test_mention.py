"""Unit tests for MentionBuilder utilities."""
from datetime import datetime, timezone

from parrot.integrations.telegram.crew.mention import (
    format_reply,
    mention_from_card,
    mention_from_user_id,
    mention_from_username,
)
from parrot.integrations.telegram.crew.agent_card import AgentCard


class TestMentionBuilder:
    def test_from_username(self):
        assert mention_from_username("test_bot") == "@test_bot"

    def test_from_username_idempotent(self):
        assert mention_from_username("@test_bot") == "@test_bot"

    def test_from_username_double_at(self):
        assert mention_from_username("@@test_bot") == "@test_bot"

    def test_from_user_id(self):
        result = mention_from_user_id(12345, "TestUser")
        assert "12345" in result
        assert "TestUser" in result
        assert 'href="tg://user?id=12345"' in result

    def test_from_user_id_html_format(self):
        result = mention_from_user_id(99, "Alice")
        assert result == '<a href="tg://user?id=99">Alice</a>'

    def test_from_card(self):
        card = AgentCard(
            agent_id="a1",
            agent_name="Test",
            telegram_username="test_bot",
            telegram_user_id=123,
            model="test",
            joined_at=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
        )
        assert mention_from_card(card) == "@test_bot"

    def test_format_reply(self):
        result = format_reply("@user", "Here is your answer")
        assert result.startswith("@user")
        assert "Here is your answer" in result

    def test_format_reply_newline_separated(self):
        result = format_reply("@bot", "Response text")
        assert result == "@bot\nResponse text"

    def test_format_reply_multiline_text(self):
        result = format_reply("@bot", "Line 1\nLine 2")
        assert result == "@bot\nLine 1\nLine 2"
