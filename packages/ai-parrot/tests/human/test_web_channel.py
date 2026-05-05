"""Unit tests for WebHumanChannel."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.human.channels.web import WebHumanChannel
from parrot.human.models import HumanInteraction, InteractionType, ChoiceOption


@pytest.fixture
def fake_socket_manager():
    """Fake UserSocketManager that records all notify_channel calls."""
    manager = MagicMock()
    manager.notify_channel = AsyncMock(return_value=True)
    return manager


@pytest.fixture
def web_channel(fake_socket_manager):
    return WebHumanChannel(socket_manager=fake_socket_manager)


@pytest.mark.asyncio
class TestWebHumanChannel:
    async def test_web_channel_send_approval(self, web_channel, fake_socket_manager):
        """send_interaction with APPROVAL produces correct payload shape."""
        interaction = HumanInteraction(
            interaction_type=InteractionType.APPROVAL,
            question="Approve this?",
            context="test",
        )
        result = await web_channel.send_interaction(interaction, "sess-123")
        assert result is True
        assert fake_socket_manager.notify_channel.called
        call_args = fake_socket_manager.notify_channel.call_args
        channel, payload = call_args[0]
        assert channel == "sess-123"
        assert payload["type"] == "hitl:question"
        assert payload["interaction_type"] == "approval"
        assert payload["question"] == "Approve this?"

    async def test_web_channel_send_single_choice(self, web_channel, fake_socket_manager):
        """send_interaction with SINGLE_CHOICE includes options."""
        options = [
            ChoiceOption(key="a", label="Option A"),
            ChoiceOption(key="b", label="Option B"),
        ]
        interaction = HumanInteraction(
            interaction_type=InteractionType.SINGLE_CHOICE,
            question="Pick one",
            options=options,
        )
        result = await web_channel.send_interaction(interaction, "sess-123")
        assert result is True
        call_args = fake_socket_manager.notify_channel.call_args
        payload = call_args[0][1]
        assert payload["options"] == [
            {"key": "a", "label": "Option A", "description": None},
            {"key": "b", "label": "Option B", "description": None},
        ]

    async def test_web_channel_send_form(self, web_channel, fake_socket_manager):
        """send_interaction with FORM includes form_schema."""
        form_schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        interaction = HumanInteraction(
            interaction_type=InteractionType.FORM,
            question="Fill out",
            form_schema=form_schema,
        )
        result = await web_channel.send_interaction(interaction, "sess-123")
        assert result is True
        call_args = fake_socket_manager.notify_channel.call_args
        payload = call_args[0][1]
        assert payload["form_schema"] == form_schema

    async def test_web_channel_returns_false_when_channel_missing(self, web_channel, fake_socket_manager):
        """send_interaction returns False if notify_channel returns False."""
        fake_socket_manager.notify_channel = AsyncMock(return_value=False)
        interaction = HumanInteraction(
            interaction_type=InteractionType.APPROVAL,
            question="Test",
        )
        result = await web_channel.send_interaction(interaction, "sess-123")
        assert result is False

    async def test_web_channel_cancel(self, web_channel, fake_socket_manager):
        """cancel_interaction emits hitl:cancel payload."""
        await web_channel.cancel_interaction("uuid-123", "sess-123")
        call_args = fake_socket_manager.notify_channel.call_args
        channel, payload = call_args[0]
        assert channel == "sess-123"
        assert payload["type"] == "hitl:cancel"
        assert payload["interaction_id"] == "uuid-123"

    async def test_web_channel_register_response_handler(self, web_channel):
        """register_response_handler stores callback without raising."""
        callback = AsyncMock()
        await web_channel.register_response_handler(callback)
        # Should not raise and callback should be stored
        assert web_channel._response_callback is not None

    async def test_web_channel_send_notification(self, web_channel, fake_socket_manager):
        """send_notification emits hitl:notification payload."""
        await web_channel.send_notification("sess-123", "Hello!")
        call_args = fake_socket_manager.notify_channel.call_args
        channel, payload = call_args[0]
        assert channel == "sess-123"
        assert payload["type"] == "hitl:notification"
        assert payload["message"] == "Hello!"

    async def test_web_channel_type(self, web_channel):
        """channel_type class attribute is 'web'."""
        assert web_channel.channel_type == "web"
        assert WebHumanChannel.channel_type == "web"

    async def test_web_channel_payload_has_deadline(self, web_channel, fake_socket_manager):
        """send_interaction payload includes a deadline field."""
        interaction = HumanInteraction(
            interaction_type=InteractionType.FREE_TEXT,
            question="What is your name?",
        )
        await web_channel.send_interaction(interaction, "sess-xyz")
        call_args = fake_socket_manager.notify_channel.call_args
        payload = call_args[0][1]
        assert "deadline" in payload
        assert payload["timeout"] == 7200.0
