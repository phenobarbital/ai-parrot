"""Tests for Matrix reply-to threading support (TASK-1295 — FEAT-195)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# MatrixAppService reply-to tests
# ---------------------------------------------------------------------------


class TestSendReplyAsAgent:
    """Tests for MatrixAppService.send_reply_as_agent()."""

    @pytest.fixture
    def mock_appservice(self):
        """MatrixAppService instance with mocked internals."""
        with patch("parrot.integrations.matrix.appservice.HAS_MAUTRIX", True):
            from parrot.integrations.matrix.models import MatrixAppServiceConfig
            from parrot.integrations.matrix.appservice import MatrixAppService

            config = MatrixAppServiceConfig(as_token="a", hs_token="h")
            svc = MatrixAppService.__new__(MatrixAppService)
            svc._config = config
            svc._appservice = MagicMock()
            svc._registered_agents = {"analyst": "@analyst:test.local"}
            svc._agent_rooms = {}
            svc._event_callback = None

            import logging
            svc.logger = logging.getLogger("test.appservice")

            # Mock intent
            mock_intent = AsyncMock()
            mock_intent.send_message = AsyncMock(return_value="$reply_event_id")
            svc._appservice.intent = MagicMock()
            svc._appservice.intent.user = MagicMock(return_value=mock_intent)

            svc._mock_intent = mock_intent
            return svc

    @pytest.mark.asyncio
    async def test_send_reply_as_agent_sets_relation(self, mock_appservice):
        """send_reply_as_agent includes m.in_reply_to in content."""
        with patch("parrot.integrations.matrix.appservice.HAS_MAUTRIX", True):
            with patch("parrot.integrations.matrix.appservice.RoomID", side_effect=lambda x: x):
                sent_content = None

                async def capture_send(room_id, content):
                    nonlocal sent_content
                    sent_content = content
                    return "$reply_event_123"

                mock_appservice._mock_intent.send_message = capture_send
                mock_appservice._get_intent = lambda mxid: mock_appservice._mock_intent

                event_id = await mock_appservice.send_reply_as_agent(
                    "analyst", "!room:test.local", "reply text", "$orig_event"
                )

                assert sent_content is not None
                assert sent_content["m.relates_to"]["m.in_reply_to"]["event_id"] == "$orig_event"

    @pytest.mark.asyncio
    async def test_send_reply_as_agent_unregistered_raises(self, mock_appservice):
        """send_reply_as_agent raises ValueError for unknown agent."""
        with pytest.raises(ValueError, match="not registered"):
            await mock_appservice.send_reply_as_agent(
                "unknown_agent", "!room:test.local", "text", "$event"
            )

    @pytest.mark.asyncio
    async def test_send_reply_as_bot_sets_relation(self, mock_appservice):
        """send_reply_as_bot includes m.in_reply_to in content."""
        with patch("parrot.integrations.matrix.appservice.HAS_MAUTRIX", True):
            with patch("parrot.integrations.matrix.appservice.RoomID", side_effect=lambda x: x):
                sent_content = None

                async def capture_send(room_id, content):
                    nonlocal sent_content
                    sent_content = content
                    return "$bot_reply_event"

                mock_bot_intent = MagicMock()
                mock_bot_intent.send_message = capture_send
                # bot_intent is a property — patch it on the instance via type mock
                with patch.object(
                    type(mock_appservice), "bot_intent",
                    new_callable=lambda: property(lambda self: mock_bot_intent)
                ):
                    event_id = await mock_appservice.send_reply_as_bot(
                        "!room:test.local", "bot reply", "$orig_bot_event"
                    )

                assert sent_content is not None
                assert sent_content["m.relates_to"]["m.in_reply_to"]["event_id"] == "$orig_bot_event"


# ---------------------------------------------------------------------------
# mention.py helper tests
# ---------------------------------------------------------------------------


class TestBuildReplyContent:
    """Tests for build_reply_content() helper in mention.py."""

    def test_reply_content_structure(self):
        """build_reply_content returns correct m.relates_to structure."""
        from parrot.integrations.matrix.crew.mention import build_reply_content

        result = build_reply_content("Hello world", "$event_abc")

        assert result["body"] == "Hello world"
        assert "m.relates_to" in result
        assert result["m.relates_to"]["m.in_reply_to"]["event_id"] == "$event_abc"

    def test_reply_content_preserves_body(self):
        """build_reply_content stores message text in body."""
        from parrot.integrations.matrix.crew.mention import build_reply_content

        text = "This is a multiline\nresponse text"
        result = build_reply_content(text, "$some_event")
        assert result["body"] == text


# ---------------------------------------------------------------------------
# _AppServiceBotClient reply tests
# ---------------------------------------------------------------------------


class TestAppServiceBotClientSendReply:
    """Tests for _AppServiceBotClient.send_reply()."""

    @pytest.fixture
    def bot_client(self):
        """_AppServiceBotClient with mocked appservice."""
        from parrot.integrations.matrix.crew.transport import _AppServiceBotClient

        mock_svc = AsyncMock()
        mock_svc.send_reply_as_bot = AsyncMock(return_value="$bot_reply")
        client = _AppServiceBotClient(mock_svc, "!default_room:server")
        client._mock_svc = mock_svc
        return client

    @pytest.mark.asyncio
    async def test_send_reply_delegates_to_appservice(self, bot_client):
        """_AppServiceBotClient.send_reply delegates to send_reply_as_bot."""
        result = await bot_client.send_reply(
            "!room:server", "reply text", "$orig_event"
        )
        bot_client._mock_svc.send_reply_as_bot.assert_called_once_with(
            "!room:server", "reply text", "$orig_event"
        )
        assert result == "$bot_reply"

    @pytest.mark.asyncio
    async def test_send_reply_returns_event_id(self, bot_client):
        """send_reply returns the event ID from appservice."""
        bot_client._mock_svc.send_reply_as_bot = AsyncMock(return_value="$event_xyz")
        result = await bot_client.send_reply("!room:server", "text", "$ref")
        assert result == "$event_xyz"
