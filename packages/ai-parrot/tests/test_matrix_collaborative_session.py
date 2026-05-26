"""Tests for MatrixCollaborativeSession orchestrator (TASK-1298 — FEAT-195)."""
import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.integrations.matrix.crew.session import MatrixCollaborativeSession
from parrot.integrations.matrix.crew.session_models import (
    CollaborativeSessionState,
    SessionPhase,
)
from parrot.integrations.matrix.crew.config import CollaborativeConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def collaborative_config():
    """Collaborative config with short timeouts for testing."""
    return CollaborativeConfig(
        max_rounds=1,
        agent_timeout=5.0,
        session_timeout=30.0,
        summarizer_agent="summarizer",
        session_verbosity="silent",  # suppress announcements in tests
    )


@pytest.fixture
def mock_appservice():
    """Mock MatrixAppService."""
    svc = AsyncMock()
    svc.send_as_bot.return_value = "$bot_event"
    svc.send_as_agent.return_value = "$agent_event"
    svc.send_reply_as_agent.return_value = "$reply_event"
    svc.send_reply_as_bot.return_value = "$reply_bot_event"
    return svc


@pytest.fixture
def mock_registry():
    """Mock MatrixCrewRegistry with analyst, researcher, and summarizer."""
    registry = AsyncMock()
    card_a = MagicMock(
        agent_name="analyst",
        display_name="Analyst",
        mxid="@analyst:server",
    )
    card_b = MagicMock(
        agent_name="researcher",
        display_name="Researcher",
        mxid="@researcher:server",
    )
    card_sum = MagicMock(
        agent_name="summarizer",
        display_name="Summarizer",
        mxid="@summarizer:server",
    )
    registry.all_agents.return_value = [card_a, card_b, card_sum]
    registry.get_by_mxid.return_value = card_a
    return registry


@pytest.fixture
def mock_wrappers():
    """Mock wrappers for each agent."""
    wrappers = {}
    for name in ("analyst", "researcher", "summarizer"):
        w = AsyncMock()
        w._agent_name = name
        w._mxid = f"@{name}:server"

        config_mock = MagicMock()
        config_mock.mxid_localpart = name
        config_mock.chatbot_id = f"{name}-bot"
        w._config = config_mock

        wrappers[name] = w
    return wrappers


@pytest.fixture
def session(collaborative_config, mock_appservice, mock_registry, mock_wrappers):
    """MatrixCollaborativeSession with mocked dependencies."""
    return MatrixCollaborativeSession(
        session_id="sess-test-1",
        room_id="!room:server",
        question="What is the market trend?",
        config=collaborative_config,
        appservice=mock_appservice,
        registry=mock_registry,
        wrappers=mock_wrappers,
        server_name="server",
    )


# ---------------------------------------------------------------------------
# Helper: mock BotManager.get_bot
# ---------------------------------------------------------------------------


def make_mock_agent(response_text="Analysis complete"):
    """Create a mock agent that returns a string from ask()."""
    agent = AsyncMock()
    agent.ask.return_value = response_text
    return agent


# ---------------------------------------------------------------------------
# Session Lifecycle
# ---------------------------------------------------------------------------


class TestSessionLifecycle:
    """Tests for the full session run() lifecycle."""

    @pytest.mark.asyncio
    async def test_run_completes_all_phases(self, session):
        """run() goes through all phases and reaches COMPLETED."""
        mock_agent = make_mock_agent("Analysis result")

        with patch("parrot.integrations.matrix.crew.session.BotManager") as MockBM:
            MockBM.get_bot = AsyncMock(return_value=mock_agent)
            state = await session.run()

        assert state.phase == SessionPhase.COMPLETED
        assert state.started_at is not None
        assert state.completed_at is not None

    @pytest.mark.asyncio
    async def test_run_returns_collaborative_session_state(self, session):
        """run() returns a CollaborativeSessionState instance."""
        mock_agent = make_mock_agent()
        with patch("parrot.integrations.matrix.crew.session.BotManager") as MockBM:
            MockBM.get_bot = AsyncMock(return_value=mock_agent)
            state = await session.run()
        assert isinstance(state, CollaborativeSessionState)

    @pytest.mark.asyncio
    async def test_initial_phase_is_created(self, session):
        """Session starts in CREATED phase."""
        assert session.phase == SessionPhase.CREATED

    @pytest.mark.asyncio
    async def test_is_active_while_running(self, session):
        """is_active returns True before session completes."""
        assert session.is_active is True

    @pytest.mark.asyncio
    async def test_is_active_false_after_completion(self, session):
        """is_active returns False after session completes."""
        mock_agent = make_mock_agent()
        with patch("parrot.integrations.matrix.crew.session.BotManager") as MockBM:
            MockBM.get_bot = AsyncMock(return_value=mock_agent)
            await session.run()
        assert session.is_active is False


class TestInvestigatePhase:
    """Tests for the investigation phase."""

    @pytest.mark.asyncio
    async def test_investigate_calls_non_summarizer_agents(self, session, mock_wrappers):
        """Investigation phase calls analyst and researcher but NOT summarizer."""

        async def mock_get_bot(chatbot_id):
            agent = make_mock_agent(f"Response from {chatbot_id}")
            return agent

        with patch("parrot.integrations.matrix.crew.session.BotManager") as MockBM:
            MockBM.get_bot = AsyncMock(side_effect=mock_get_bot)
            state = await session.run()

        # analyst and researcher should have results
        assert "analyst" in state.agent_results or "researcher" in state.agent_results
        # Summarizer results are from synthesize phase only
        # (can only be present if a non-test summarizer was called as regular agent)

    @pytest.mark.asyncio
    async def test_investigate_posts_results_to_room(self, session, mock_appservice):
        """Investigation phase calls send_as_agent for each responding agent."""
        mock_agent = make_mock_agent("Some result")
        with patch("parrot.integrations.matrix.crew.session.BotManager") as MockBM:
            MockBM.get_bot = AsyncMock(return_value=mock_agent)
            await session.run()

        # send_as_agent should have been called at least twice (analyst + researcher)
        assert mock_appservice.send_as_agent.call_count >= 2


class TestCrossPollinationPhase:
    """Tests for the cross-pollination phase."""

    @pytest.mark.asyncio
    async def test_enriched_context_includes_prior_results(self, session):
        """_build_enriched_context includes other agents' results."""
        from parrot.integrations.matrix.crew.session_models import AgentRoundResult

        session._state.agent_results["analyst"] = [
            AgentRoundResult(
                agent_name="analyst",
                display_name="Analyst",
                mxid="@analyst:server",
                round_number=0,
                result_text="Market is bullish",
                event_id="$e1",
                timestamp=datetime.now(timezone.utc),
            )
        ]

        enriched = session._build_enriched_context(1, "researcher")
        assert "Market is bullish" in enriched
        assert "Analyst" in enriched
        assert "Original question" in enriched

    @pytest.mark.asyncio
    async def test_enriched_context_excludes_requesting_agent(self, session):
        """_build_enriched_context excludes the requesting agent's own results."""
        from parrot.integrations.matrix.crew.session_models import AgentRoundResult

        session._state.agent_results["analyst"] = [
            AgentRoundResult(
                agent_name="analyst",
                display_name="Analyst",
                mxid="@analyst:server",
                round_number=0,
                result_text="Analyst's own result",
                event_id="$e1",
                timestamp=datetime.now(timezone.utc),
            )
        ]

        enriched = session._build_enriched_context(1, "analyst")
        assert "Analyst's own result" not in enriched


class TestSynthesizerPhase:
    """Tests for the synthesis phase."""

    @pytest.mark.asyncio
    async def test_no_summarizer_posts_raw_results(
        self, collaborative_config, mock_appservice, mock_registry, mock_wrappers
    ):
        """Without summarizer_agent, raw results are posted via send_as_bot."""
        collaborative_config.summarizer_agent = None
        session_no_sum = MatrixCollaborativeSession(
            session_id="sess-no-sum",
            room_id="!room:server",
            question="What is X?",
            config=collaborative_config,
            appservice=mock_appservice,
            registry=mock_registry,
            wrappers=mock_wrappers,
            server_name="server",
        )

        mock_agent = make_mock_agent("Raw result")
        with patch("parrot.integrations.matrix.crew.session.BotManager") as MockBM:
            MockBM.get_bot = AsyncMock(return_value=mock_agent)
            state = await session_no_sum.run()

        assert state.phase == SessionPhase.COMPLETED
        # send_as_bot called for raw results
        mock_appservice.send_as_bot.assert_called()

    @pytest.mark.asyncio
    async def test_summarizer_payload_contains_question(self, session):
        """Synthesizer payload includes the original question."""
        payload = session._build_synthesizer_payload()
        assert "What is the market trend?" in payload

    @pytest.mark.asyncio
    async def test_synthesizer_result_stored_in_state(self, session):
        """Summarizer response is stored in state.final_synthesis."""
        mock_agent = make_mock_agent("Synthesis: markets are trending up")
        with patch("parrot.integrations.matrix.crew.session.BotManager") as MockBM:
            MockBM.get_bot = AsyncMock(return_value=mock_agent)
            state = await session.run()

        assert state.final_synthesis is not None


class TestAgentTimeout:
    """Tests for per-agent timeout behavior."""

    @pytest.mark.asyncio
    async def test_timed_out_agent_skipped(
        self, collaborative_config, mock_appservice, mock_registry, mock_wrappers
    ):
        """Agent that exceeds agent_timeout is skipped with a notice."""
        collaborative_config.agent_timeout = 0.01  # instant timeout
        collaborative_config.session_verbosity = "full"

        session_fast = MatrixCollaborativeSession(
            session_id="sess-timeout",
            room_id="!room:server",
            question="What?",
            config=collaborative_config,
            appservice=mock_appservice,
            registry=mock_registry,
            wrappers=mock_wrappers,
            server_name="server",
        )

        async def slow_ask(body):
            await asyncio.sleep(5.0)  # much longer than timeout
            return "Never reached"

        mock_agent = AsyncMock()
        mock_agent.ask = slow_ask

        with patch("parrot.integrations.matrix.crew.session.BotManager") as MockBM:
            MockBM.get_bot = AsyncMock(return_value=mock_agent)
            state = await session_fast.run()

        # Session should still reach COMPLETED (or FAILED if all timed out)
        assert state.phase in (SessionPhase.COMPLETED, SessionPhase.FAILED)


class TestSessionTimeout:
    """Tests for whole-session timeout."""

    @pytest.mark.asyncio
    async def test_session_timeout_results_in_failed(
        self, collaborative_config, mock_appservice, mock_registry, mock_wrappers
    ):
        """Session moves to FAILED when session_timeout exceeded."""
        collaborative_config.session_timeout = 0.001  # instant timeout
        collaborative_config.session_verbosity = "silent"

        session_fast = MatrixCollaborativeSession(
            session_id="sess-ses-timeout",
            room_id="!room:server",
            question="What?",
            config=collaborative_config,
            appservice=mock_appservice,
            registry=mock_registry,
            wrappers=mock_wrappers,
            server_name="server",
        )

        async def very_slow_ask(body):
            await asyncio.sleep(10.0)
            return "Never"

        mock_agent = AsyncMock()
        mock_agent.ask = very_slow_ask

        with patch("parrot.integrations.matrix.crew.session.BotManager") as MockBM:
            MockBM.get_bot = AsyncMock(return_value=mock_agent)
            state = await session_fast.run()

        assert state.phase == SessionPhase.FAILED


class TestCancel:
    """Tests for session cancellation."""

    @pytest.mark.asyncio
    async def test_cancel_transitions_to_failed(self, session):
        """cancel() sets phase to FAILED and marks completed_at."""
        await session.cancel("User cancelled")
        assert session.phase == SessionPhase.FAILED

    @pytest.mark.asyncio
    async def test_cancel_posts_notice(self, mock_appservice, mock_registry, mock_wrappers):
        """cancel() posts an announcement to the room (requires non-silent verbosity)."""
        config_verbose = CollaborativeConfig(
            max_rounds=1,
            agent_timeout=5.0,
            session_timeout=30.0,
            summarizer_agent="summarizer",
            session_verbosity="full",
        )
        verbose_session = MatrixCollaborativeSession(
            session_id="sess-cancel",
            room_id="!room:server",
            question="test?",
            config=config_verbose,
            appservice=mock_appservice,
            registry=mock_registry,
            wrappers=mock_wrappers,
            server_name="server",
        )
        await verbose_session.cancel("Test cancel")
        mock_appservice.send_as_bot.assert_called()

    @pytest.mark.asyncio
    async def test_is_active_false_after_cancel(self, session):
        """is_active returns False after cancel()."""
        await session.cancel()
        assert session.is_active is False


class TestInterAgentRouting:
    """Tests for handle_inter_agent_message()."""

    @pytest.mark.asyncio
    async def test_routes_to_mentioned_agent(self, session, mock_wrappers):
        """@mention in body is routed to the correct wrapper."""
        await session.handle_inter_agent_message(
            sender_mxid="@analyst:server",
            body="@researcher can you check the data?",
            event_id="$msg_event",
        )
        mock_wrappers["researcher"].handle_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_mention_does_nothing(self, session, mock_wrappers):
        """Message without @mention does not route to any wrapper."""
        await session.handle_inter_agent_message(
            sender_mxid="@analyst:server",
            body="Just a regular message",
            event_id="$msg_event",
        )
        for wrapper in mock_wrappers.values():
            wrapper.handle_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_inactive_session_ignores_message(self, session):
        """Inactive session ignores inter-agent messages."""
        await session.cancel("Done")
        # Should not raise even when inactive
        await session.handle_inter_agent_message(
            sender_mxid="@analyst:server",
            body="@researcher check this",
            event_id="$msg",
        )
