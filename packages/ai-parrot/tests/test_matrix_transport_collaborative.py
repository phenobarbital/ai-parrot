"""Tests for MatrixCrewTransport collaborative integration (TASK-1299 — FEAT-195)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.integrations.matrix.crew.transport import MatrixCrewTransport
from parrot.integrations.matrix.crew.config import CollaborativeConfig, MatrixCrewConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(with_collaborative: bool = True) -> MatrixCrewConfig:
    """Build a minimal MatrixCrewConfig for testing."""
    kwargs = {
        "homeserver_url": "http://localhost:8008",
        "server_name": "server",
        "as_token": "as_token",
        "hs_token": "hs_token",
        "bot_mxid": "@bot:server",
        "general_room_id": "!general:server",
    }
    if with_collaborative:
        kwargs["collaborative"] = CollaborativeConfig(
            command_prefix="!investigate",
            max_rounds=1,
            agent_timeout=5.0,
            session_timeout=30.0,
            summarizer_agent=None,
            session_verbosity="silent",
        )
    return MatrixCrewConfig(**kwargs)


def _make_transport(with_collaborative: bool = True) -> MatrixCrewTransport:
    """Build a MatrixCrewTransport with mocked appservice."""
    transport = MatrixCrewTransport(_make_config(with_collaborative))
    transport._appservice = AsyncMock()
    transport._appservice.send_as_bot.return_value = "$bot_event"
    # populate agent mxid set
    transport._agent_mxids = {"@analyst:server", "@bot:server"}
    # minimal wrappers
    wrapper_a = AsyncMock()
    wrapper_a._config = MagicMock(mxid_localpart="analyst", chatbot_id="analyst-bot")
    transport._wrappers = {"analyst": wrapper_a}
    return transport


# ---------------------------------------------------------------------------
# Tests for _is_collaborative_command
# ---------------------------------------------------------------------------


class TestIsCollaborativeCommand:
    """Unit tests for the _is_collaborative_command() helper."""

    def test_detect_command(self):
        """_is_collaborative_command detects !investigate prefix."""
        transport = _make_transport()
        question = transport._is_collaborative_command("!investigate What is X?")
        assert question == "What is X?"

    def test_detect_command_with_extra_whitespace(self):
        """Strips leading/trailing whitespace from question."""
        transport = _make_transport()
        question = transport._is_collaborative_command("!investigate   market trend   ")
        assert question == "market trend"

    def test_detect_custom_prefix(self):
        """Custom command_prefix is respected."""
        transport = MatrixCrewTransport(_make_config())
        transport._config.collaborative.command_prefix = "!collab"
        transport._appservice = AsyncMock()
        question = transport._is_collaborative_command("!collab What is Y?")
        assert question == "What is Y?"

    def test_non_command_ignored(self):
        """Regular messages don't trigger collaborative sessions."""
        transport = _make_transport()
        assert transport._is_collaborative_command("Hello world") is None

    def test_empty_question_ignored(self):
        """!investigate with no question text returns None."""
        transport = _make_transport()
        assert transport._is_collaborative_command("!investigate") is None
        assert transport._is_collaborative_command("!investigate   ") is None

    def test_no_collaborative_config_returns_none(self):
        """When collaborative is None, always returns None."""
        transport = _make_transport(with_collaborative=False)
        assert transport._is_collaborative_command("!investigate What?") is None

    def test_partial_prefix_not_matched(self):
        """Partial prefix match does not trigger command."""
        transport = _make_transport()
        assert transport._is_collaborative_command("!inv What?") is None


# ---------------------------------------------------------------------------
# Tests for transport collaborative routing
# ---------------------------------------------------------------------------


class TestTransportCollaborativeRouting:
    """Integration tests for collaborative session routing in on_room_message."""

    @pytest.mark.asyncio
    async def test_investigate_creates_session(self):
        """!investigate from a human creates and runs a session."""
        transport = _make_transport()

        mock_session = AsyncMock()
        mock_session.is_active = True
        mock_session.run = AsyncMock(return_value=MagicMock())

        with patch(
            "parrot.integrations.matrix.crew.transport.MatrixCollaborativeSession",
            return_value=mock_session,
        ):
            await transport.on_room_message(
                room_id="!room:server",
                sender="@human:server",
                body="!investigate What is the market trend?",
                event_id="$evt1",
            )

        mock_session.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_removed_after_run(self):
        """Session is cleaned up from _active_sessions after run completes."""
        transport = _make_transport()

        mock_session = AsyncMock()
        mock_session.is_active = True
        mock_session.run = AsyncMock(return_value=MagicMock())

        with patch(
            "parrot.integrations.matrix.crew.transport.MatrixCollaborativeSession",
            return_value=mock_session,
        ):
            await transport.on_room_message(
                room_id="!room:server",
                sender="@human:server",
                body="!investigate What is the market trend?",
                event_id="$evt1",
            )

        assert "!room:server" not in transport._active_sessions

    @pytest.mark.asyncio
    async def test_concurrent_session_rejected(self):
        """Second !investigate in same room rejected while session active."""
        transport = _make_transport()

        # Manually inject an active session for the room
        mock_existing = MagicMock()
        mock_existing.is_active = True
        transport._active_sessions["!room:server"] = mock_existing

        await transport.on_room_message(
            room_id="!room:server",
            sender="@human:server",
            body="!investigate Another question?",
            event_id="$evt2",
        )

        # send_as_bot should have been called with the rejection message
        transport._appservice.send_as_bot.assert_called_once()
        call_args = transport._appservice.send_as_bot.call_args
        assert "already active" in call_args[0][1].lower()

    @pytest.mark.asyncio
    async def test_no_collaborative_config_ignores_command(self):
        """Without collaborative config, !investigate is not triggered."""
        transport = _make_transport(with_collaborative=False)

        # For this test we just verify no session is created
        await transport.on_room_message(
            room_id="!room:server",
            sender="@human:server",
            body="!investigate What is X?",
            event_id="$evt3",
        )

        # No session should exist in _active_sessions
        assert "!room:server" not in transport._active_sessions

    @pytest.mark.asyncio
    async def test_agent_mention_routed_during_session(self):
        """Agent @mention during active session bypasses self-filter."""
        transport = _make_transport()

        mock_session = AsyncMock()
        mock_session.is_active = True
        transport._active_sessions["!room:server"] = mock_session

        await transport.on_room_message(
            room_id="!room:server",
            sender="@analyst:server",  # in _agent_mxids
            body="@researcher can you check this?",
            event_id="$evt4",
        )

        mock_session.handle_inter_agent_message.assert_called_once_with(
            "@analyst:server",
            "@researcher can you check this?",
            "$evt4",
        )

    @pytest.mark.asyncio
    async def test_agent_no_mention_filtered_during_session(self):
        """Agent message without @mention during active session is still filtered."""
        transport = _make_transport()

        mock_session = AsyncMock()
        mock_session.is_active = True
        transport._active_sessions["!room:server"] = mock_session

        await transport.on_room_message(
            room_id="!room:server",
            sender="@analyst:server",
            body="Just a regular message with no mention",
            event_id="$evt5",
        )

        # handle_inter_agent_message should NOT have been called
        mock_session.handle_inter_agent_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_agent_messages_filtered_without_session(self):
        """Agent messages in rooms with no active session are still filtered (unchanged)."""
        transport = _make_transport()
        # No session in _active_sessions

        wrapper = transport._wrappers.get("analyst")

        await transport.on_room_message(
            room_id="!room:server",
            sender="@analyst:server",
            body="Some message",
            event_id="$evt6",
        )

        # No wrapper should have been called
        wrapper.handle_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_normal_routing_unaffected(self):
        """@agent question routing works identically with collaborative config present."""
        transport = _make_transport(with_collaborative=True)
        # Add agent entry to config.agents for @mention routing
        entry = MagicMock()
        entry.mxid_localpart = "analyst"
        transport._config.agents = {"analyst": entry}

        await transport.on_room_message(
            room_id="!room:server",
            sender="@human:server",
            body="@analyst what is X?",
            event_id="$evt7",
        )

        wrapper = transport._wrappers.get("analyst")
        wrapper.handle_message.assert_called_once_with(
            "!room:server", "@human:server", "@analyst what is X?", "$evt7"
        )

    @pytest.mark.asyncio
    async def test_session_cleanup_on_failure(self):
        """Session is removed from _active_sessions even on exception."""
        transport = _make_transport()

        mock_session = AsyncMock()
        mock_session.is_active = True
        mock_session.run = AsyncMock(side_effect=RuntimeError("Session exploded"))

        with patch(
            "parrot.integrations.matrix.crew.transport.MatrixCollaborativeSession",
            return_value=mock_session,
        ):
            # run() raises — session must still be cleaned up
            with pytest.raises(RuntimeError, match="Session exploded"):
                await transport.on_room_message(
                    room_id="!room:server",
                    sender="@human:server",
                    body="!investigate Test question",
                    event_id="$evt8",
                )

        assert "!room:server" not in transport._active_sessions

    @pytest.mark.asyncio
    async def test_inactive_session_does_not_bypass_self_filter(self):
        """Inactive (completed) session does not bypass self-filter for agent messages."""
        transport = _make_transport()

        mock_session = MagicMock()
        mock_session.is_active = False  # session already completed
        transport._active_sessions["!room:server"] = mock_session

        await transport.on_room_message(
            room_id="!room:server",
            sender="@analyst:server",
            body="@researcher check this",
            event_id="$evt9",
        )

        # Even with @mention, inactive session should not route
        mock_session.handle_inter_agent_message.assert_not_called()
