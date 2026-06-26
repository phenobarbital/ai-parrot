"""
Unit tests for ParrotM365Agent identity extraction.

Covers FEAT-261 Module 2 (Identity Extraction).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


class MockFromProperty:
    def __init__(self, channel_id: str, aad_object_id: str = None):
        self.id = channel_id
        self.aad_object_id = aad_object_id
        self.name = "Test User"


class MockActivity:
    def __init__(self, from_id="user-123", aad_id=None, conv_id="conv-456"):
        self.type = "message"
        self.text = "Hello"
        self.from_property = MockFromProperty(from_id, aad_id)
        self.conversation = MagicMock(id=conv_id)


class TestIdentityExtraction:
    """Tests for _extract_user_id and _build_user_context."""

    def _make_agent(self):
        from parrot.integrations.msagentsdk.agent import ParrotM365Agent

        mock_bot = AsyncMock()
        return ParrotM365Agent(parrot_agent=mock_bot)

    def test_identity_aad_object_id(self):
        """Returns aad_object_id when present on from_property."""
        agent = self._make_agent()
        activity = MockActivity(
            from_id="user-channel-123",
            aad_id="00000000-0000-0000-0000-000000000001",
        )
        uid = agent._extract_user_id(activity)
        assert uid == "00000000-0000-0000-0000-000000000001"

    def test_identity_fallback_channel_id(self):
        """Falls back to from_property.id when aad_object_id is absent."""
        agent = self._make_agent()
        activity = MockActivity(from_id="user-999")
        uid = agent._extract_user_id(activity)
        assert uid == "user-999"

    def test_identity_no_from_property(self):
        """Returns 'anonymous' when from_property is None."""
        agent = self._make_agent()
        activity = MagicMock()
        activity.from_property = None
        uid = agent._extract_user_id(activity)
        assert uid == "anonymous"

    def test_identity_aad_object_id_camelcase(self):
        """Also recognises aadObjectId (camelCase) SDK variant."""
        agent = self._make_agent()
        activity = MagicMock()
        from_prop = MagicMock()
        from_prop.aad_object_id = None
        from_prop.aadObjectId = "camel-case-uuid"
        from_prop.id = "channel-id"
        activity.from_property = from_prop
        uid = agent._extract_user_id(activity)
        assert uid == "camel-case-uuid"

    def test_build_user_context_channel(self):
        """_build_user_context returns UserContext with channel='msagentsdk'."""
        agent = self._make_agent()
        activity = MockActivity(
            from_id="user-1",
            aad_id="00000000-0000-0000-0000-000000000001",
            conv_id="session-abc",
        )
        ctx = agent._build_user_context(activity)
        assert ctx.channel == "msagentsdk"
        assert ctx.user_id == "00000000-0000-0000-0000-000000000001"
        assert ctx.session_id == "session-abc"

    def test_agent_init_accepts_resolver_and_ledger(self):
        """ParrotM365Agent accepts optional resolver and audit_ledger."""
        from parrot.integrations.msagentsdk.agent import ParrotM365Agent

        mock_bot = AsyncMock()
        mock_resolver = MagicMock()
        mock_ledger = MagicMock()
        agent = ParrotM365Agent(
            parrot_agent=mock_bot,
            resolver=mock_resolver,
            audit_ledger=mock_ledger,
        )
        assert agent._resolver is mock_resolver
        assert agent._audit_ledger is mock_ledger
