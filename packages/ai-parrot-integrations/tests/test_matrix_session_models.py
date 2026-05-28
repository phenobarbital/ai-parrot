"""Tests for session state data models (TASK-1297 — FEAT-195)."""
import pytest
from datetime import datetime, timezone

from parrot.integrations.matrix.crew.session_models import (
    AgentRoundResult,
    CollaborativeSessionState,
    SessionPhase,
)


class TestSessionPhase:
    """Tests for the SessionPhase enum."""

    def test_enum_values(self):
        """SessionPhase has all required string values."""
        assert SessionPhase.CREATED == "created"
        assert SessionPhase.INVESTIGATING == "investigating"
        assert SessionPhase.CROSS_POLLINATING == "cross_pollinating"
        assert SessionPhase.SYNTHESIZING == "synthesizing"
        assert SessionPhase.COMPLETED == "completed"
        assert SessionPhase.FAILED == "failed"

    def test_is_string(self):
        """SessionPhase values are strings (str Enum)."""
        assert isinstance(SessionPhase.COMPLETED, str)
        assert SessionPhase.COMPLETED == "completed"

    def test_six_values(self):
        """SessionPhase has exactly 6 values."""
        assert len(list(SessionPhase)) == 6

    def test_comparison_with_string(self):
        """SessionPhase can be compared with plain strings."""
        assert SessionPhase.INVESTIGATING == "investigating"
        assert "completed" == SessionPhase.COMPLETED


class TestAgentRoundResult:
    """Tests for the AgentRoundResult model."""

    @pytest.fixture
    def sample_result(self):
        """A valid AgentRoundResult instance."""
        return AgentRoundResult(
            agent_name="analyst",
            display_name="Financial Analyst",
            mxid="@analyst:server",
            round_number=1,
            result_text="Analysis complete: market is bullish",
            event_id="$event_abc123",
            timestamp=datetime.now(timezone.utc),
        )

    def test_creation(self, sample_result):
        """AgentRoundResult is created correctly."""
        assert sample_result.agent_name == "analyst"
        assert sample_result.display_name == "Financial Analyst"
        assert sample_result.mxid == "@analyst:server"
        assert sample_result.round_number == 1
        assert "bullish" in sample_result.result_text
        assert sample_result.event_id == "$event_abc123"

    def test_serialization(self, sample_result):
        """AgentRoundResult serializes to dict with all fields."""
        data = sample_result.model_dump()
        assert "agent_name" in data
        assert "display_name" in data
        assert "mxid" in data
        assert "round_number" in data
        assert "result_text" in data
        assert "event_id" in data
        assert "timestamp" in data

    def test_event_id_preserved(self, sample_result):
        """event_id is stored exactly as provided."""
        assert sample_result.event_id == "$event_abc123"

    def test_timestamp_type(self, sample_result):
        """timestamp is a datetime object."""
        assert isinstance(sample_result.timestamp, datetime)

    def test_round_number_zero(self):
        """round_number=0 is valid (investigation phase)."""
        result = AgentRoundResult(
            agent_name="researcher",
            display_name="Researcher",
            mxid="@researcher:server",
            round_number=0,
            result_text="Initial findings",
            event_id="$event_000",
            timestamp=datetime.now(timezone.utc),
        )
        assert result.round_number == 0


class TestCollaborativeSessionState:
    """Tests for the CollaborativeSessionState model."""

    def test_defaults(self):
        """CollaborativeSessionState has correct default values."""
        state = CollaborativeSessionState(
            session_id="sess-abc",
            room_id="!room:server",
            question="What is the market trend?",
        )
        assert state.phase == SessionPhase.CREATED
        assert state.current_round == 0
        assert state.max_rounds == 1
        assert state.agent_results == {}
        assert state.started_at is None
        assert state.completed_at is None
        assert state.final_synthesis is None

    def test_required_fields(self):
        """session_id, room_id, and question are required."""
        with pytest.raises(Exception):
            CollaborativeSessionState(room_id="!room:server", question="test")
        with pytest.raises(Exception):
            CollaborativeSessionState(session_id="s1", question="test")
        with pytest.raises(Exception):
            CollaborativeSessionState(session_id="s1", room_id="!room:server")

    def test_phase_update(self):
        """Phase can be updated after creation."""
        state = CollaborativeSessionState(
            session_id="sess-1", room_id="!room:server", question="test"
        )
        state.phase = SessionPhase.INVESTIGATING
        assert state.phase == SessionPhase.INVESTIGATING

    def test_add_agent_result(self):
        """agent_results dict can be populated with results."""
        state = CollaborativeSessionState(
            session_id="sess-2", room_id="!room:server", question="test?"
        )
        result = AgentRoundResult(
            agent_name="analyst",
            display_name="Analyst",
            mxid="@analyst:server",
            round_number=0,
            result_text="Found data",
            event_id="$ev1",
            timestamp=datetime.now(timezone.utc),
        )
        state.agent_results["analyst"] = [result]
        assert len(state.agent_results["analyst"]) == 1
        assert state.agent_results["analyst"][0].round_number == 0

    def test_serialization(self):
        """CollaborativeSessionState serializes to dict correctly."""
        state = CollaborativeSessionState(
            session_id="sess-3",
            room_id="!room:server",
            question="What is AI?",
            max_rounds=2,
        )
        data = state.model_dump()
        assert data["session_id"] == "sess-3"
        assert data["phase"] == "created"
        assert data["max_rounds"] == 2
        assert data["agent_results"] == {}

    def test_set_final_synthesis(self):
        """final_synthesis can be set after creation."""
        state = CollaborativeSessionState(
            session_id="sess-4", room_id="!room:server", question="test"
        )
        state.final_synthesis = "The market shows upward trends."
        assert "upward" in state.final_synthesis

    def test_set_timestamps(self):
        """started_at and completed_at can be set."""
        now = datetime.now(timezone.utc)
        state = CollaborativeSessionState(
            session_id="sess-5", room_id="!room:server", question="test",
            started_at=now,
        )
        state.completed_at = now
        assert state.started_at is not None
        assert state.completed_at is not None


class TestSessionModelsExports:
    """Tests for package-level export accessibility."""

    def test_importable_from_crew_package(self):
        """Models are importable from parrot.integrations.matrix.crew."""
        from parrot.integrations.matrix.crew import (
            AgentRoundResult,
            CollaborativeSessionState,
            SessionPhase,
        )
        assert SessionPhase.CREATED == "created"
        assert AgentRoundResult is not None
        assert CollaborativeSessionState is not None
