"""Tests for Matrix integration: events, streaming, and A2A transport."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from parrot.integrations.matrix.events import (
    AgentCardEventContent,
    ParrotEventType,
    ResultEventContent,
    StatusEventContent,
    TaskEventContent,
)


# ---------------------------------------------------------------------------
# Custom Event Model Tests
# ---------------------------------------------------------------------------


class TestParrotEventTypes:
    """Verify custom event type constants."""

    def test_event_types_defined(self):
        assert ParrotEventType.AGENT_CARD == "m.parrot.agent_card"
        assert ParrotEventType.TASK == "m.parrot.task"
        assert ParrotEventType.RESULT == "m.parrot.result"
        assert ParrotEventType.STATUS == "m.parrot.status"


class TestAgentCardEventContent:
    """Tests for AgentCardEventContent model."""

    def test_minimal(self):
        card = AgentCardEventContent(
            name="TestAgent",
            description="A test agent",
        )
        assert card.name == "TestAgent"
        assert card.version == "1.0"
        assert card.protocol_version == "0.3"
        assert card.skills == []
        assert card.tags == []

    def test_full(self):
        card = AgentCardEventContent(
            name="FinanceAgent",
            description="Handles financial queries",
            version="2.0",
            skills=[{"id": "analyze", "name": "analyze", "description": "Analyze data"}],
            tags=["finance", "analysis"],
            a2a_url="https://finance.example.com",
        )
        data = card.model_dump()
        assert data["name"] == "FinanceAgent"
        assert len(data["skills"]) == 1
        assert data["a2a_url"] == "https://finance.example.com"

    def test_roundtrip(self):
        original = AgentCardEventContent(
            name="Test", description="desc", tags=["a", "b"]
        )
        data = original.model_dump()
        restored = AgentCardEventContent(**data)
        assert restored.name == original.name
        assert restored.tags == original.tags


class TestTaskEventContent:
    """Tests for TaskEventContent model."""

    def test_minimal(self):
        task = TaskEventContent(
            task_id="tid-1",
            content="What is AI?",
        )
        assert task.task_id == "tid-1"
        assert task.content == "What is AI?"
        assert task.context_id is None
        assert task.metadata == {}

    def test_with_routing(self):
        task = TaskEventContent(
            task_id="tid-2",
            content="Analyze data",
            target_agent="AnalystAgent",
            skill_id="data_analysis",
        )
        data = task.model_dump()
        assert data["target_agent"] == "AnalystAgent"
        assert data["skill_id"] == "data_analysis"


class TestResultEventContent:
    """Tests for ResultEventContent model."""

    def test_success(self):
        result = ResultEventContent(
            task_id="tid-1",
            content="AI is artificial intelligence.",
            success=True,
        )
        assert result.success is True
        assert result.error is None

    def test_failure(self):
        result = ResultEventContent(
            task_id="tid-2",
            content="",
            success=False,
            error="Agent timed out",
        )
        assert result.success is False
        assert result.error == "Agent timed out"

    def test_with_artifacts(self):
        result = ResultEventContent(
            task_id="tid-3",
            content="Analysis complete",
            artifacts=[
                {"name": "report", "data": {"revenue": 1000000}}
            ],
        )
        assert len(result.artifacts) == 1


class TestStatusEventContent:
    """Tests for StatusEventContent model."""

    def test_working(self):
        status = StatusEventContent(
            task_id="tid-1",
            state="working",
            message="Processing query...",
            progress=0.5,
        )
        assert status.state == "working"
        assert status.progress == 0.5

    def test_failed(self):
        status = StatusEventContent(
            task_id="tid-1",
            state="failed",
            message="Connection error",
        )
        data = status.model_dump()
        assert data["state"] == "failed"


# ---------------------------------------------------------------------------
# MatrixStreamHandler Tests (mocked wrapper)
# ---------------------------------------------------------------------------


class TestMatrixStreamHandler:
    """Tests for edit-based streaming handler."""

    def _make_handler(self, mock_wrapper):
        from parrot.integrations.matrix.streaming import MatrixStreamHandler
        return MatrixStreamHandler(
            mock_wrapper,
            "!test:parrot.local",
            min_edit_interval_ms=0,  # No delay for tests
            min_chars_delta=1,  # Edit on every char for tests
        )

    @pytest.mark.asyncio
    async def test_begin_stream(self):
        wrapper = MagicMock()
        wrapper.send_text = AsyncMock(return_value="$initial_event_id")

        handler = self._make_handler(wrapper)
        event_id = await handler.begin_stream("▌")

        assert event_id == "$initial_event_id"
        wrapper.send_text.assert_called_once_with(
            "!test:parrot.local", "▌"
        )

    @pytest.mark.asyncio
    async def test_end_stream(self):
        wrapper = MagicMock()
        wrapper.send_text = AsyncMock(return_value="$eid")
        wrapper.edit_message = AsyncMock(return_value="$edit_eid")

        handler = self._make_handler(wrapper)
        event_id = await handler.begin_stream()
        await handler.end_stream(event_id, "Final response text")

        wrapper.edit_message.assert_called_once_with(
            "!test:parrot.local",
            "$eid",
            "Final response text",
        )

    @pytest.mark.asyncio
    async def test_send_token_triggers_edit(self):
        wrapper = MagicMock()
        wrapper.send_text = AsyncMock(return_value="$eid")
        wrapper.edit_message = AsyncMock(return_value="$edit_eid")

        handler = self._make_handler(wrapper)
        event_id = await handler.begin_stream("▌")

        # Send a token — should trigger edit (thresholds are 0ms/1char)
        await handler.send_token(event_id, "Hello")

        # Edit should be called with accumulated text + cursor
        assert wrapper.edit_message.called
        call_args = wrapper.edit_message.call_args
        assert "Hello" in call_args[0][2]  # new_text contains "Hello"


# ---------------------------------------------------------------------------
# MatrixA2ATransport Tests (mocked wrapper)
# ---------------------------------------------------------------------------


class TestMatrixA2ATransport:
    """Tests for A2A transport over Matrix."""

    def _make_transport(self, mock_wrapper):
        from parrot.integrations.matrix.a2a_transport import MatrixA2ATransport
        return MatrixA2ATransport(mock_wrapper)

    @pytest.mark.asyncio
    async def test_publish_card(self):
        wrapper = MagicMock()
        wrapper.set_room_state = AsyncMock(return_value="$state_eid")

        transport = self._make_transport(wrapper)
        event_id = await transport.publish_card(
            "!agent-room:parrot.local",
            {"name": "TestAgent", "description": "Test"},
        )

        assert event_id == "$state_eid"
        wrapper.set_room_state.assert_called_once()
        call = wrapper.set_room_state.call_args
        assert call[0][0] == "!agent-room:parrot.local"
        assert call[0][1] == "m.parrot.agent_card"

    @pytest.mark.asyncio
    async def test_discover_card_found(self):
        wrapper = MagicMock()
        wrapper.get_room_state_event = AsyncMock(return_value={
            "name": "RemoteAgent",
            "description": "A remote agent",
        })

        transport = self._make_transport(wrapper)
        card = await transport.discover_card("!room:server")

        assert card is not None
        assert card.name == "RemoteAgent"

    @pytest.mark.asyncio
    async def test_discover_card_not_found(self):
        wrapper = MagicMock()
        wrapper.get_room_state_event = AsyncMock(return_value=None)

        transport = self._make_transport(wrapper)
        card = await transport.discover_card("!room:server")

        assert card is None

    @pytest.mark.asyncio
    async def test_send_task(self):
        wrapper = MagicMock()
        wrapper.send_event = AsyncMock(return_value="$task_eid")

        transport = self._make_transport(wrapper)
        task_id = await transport.send_task(
            "!room:server",
            "Analyze this data",
            target_agent="AnalystAgent",
        )

        # Returns a UUID task_id
        assert len(task_id) > 0
        wrapper.send_event.assert_called_once()
        call = wrapper.send_event.call_args
        assert call[0][1] == "m.parrot.task"
        content = call[0][2]
        assert content["content"] == "Analyze this data"
        assert content["target_agent"] == "AnalystAgent"

    @pytest.mark.asyncio
    async def test_send_result(self):
        wrapper = MagicMock()
        wrapper.send_event = AsyncMock(return_value="$result_eid")

        transport = self._make_transport(wrapper)
        event_id = await transport.send_result(
            "!room:server",
            "tid-1",
            "Analysis complete",
            success=True,
        )

        assert event_id == "$result_eid"
        call = wrapper.send_event.call_args
        assert call[0][1] == "m.parrot.result"
        content = call[0][2]
        assert content["task_id"] == "tid-1"
        assert content["success"] is True

    @pytest.mark.asyncio
    async def test_send_status(self):
        wrapper = MagicMock()
        wrapper.send_event = AsyncMock(return_value="$status_eid")

        transport = self._make_transport(wrapper)
        event_id = await transport.send_status(
            "!room:server",
            "tid-1",
            "working",
            message="Processing...",
            progress=0.5,
        )

        assert event_id == "$status_eid"
        call = wrapper.send_event.call_args
        content = call[0][2]
        assert content["state"] == "working"
        assert content["progress"] == 0.5
