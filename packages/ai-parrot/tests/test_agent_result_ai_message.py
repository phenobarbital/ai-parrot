"""Tests for AgentResult.ai_message field."""
import pytest
from parrot.models.crew import AgentResult
from parrot.models.responses import AIMessage
from parrot.models.basic import CompletionUsage


def _make_ai_message(**overrides) -> AIMessage:
    """Create a minimal AIMessage for testing."""
    defaults = {
        "input": "test question",
        "output": "test answer",
        "model": "test-model",
        "provider": "test",
        "usage": CompletionUsage(),
        "metadata": {},
    }
    defaults.update(overrides)
    return AIMessage(**defaults)


class TestAgentResultAIMessage:
    """Verify ai_message field on AgentResult."""

    def test_ai_message_defaults_to_none(self):
        result = AgentResult(
            agent_id="agent1",
            agent_name="Agent One",
            task="do something",
            result="text output",
            metadata={},
            execution_time=1.0,
        )
        assert result.ai_message is None

    def test_ai_message_stores_full_aimessage(self):
        msg = _make_ai_message(
            data={"revenue": [100, 200, 300]},
            code="df.sum()",
            artifacts=[{"type": "sql", "content": "SELECT *"}],
        )
        result = AgentResult(
            agent_id="agent1",
            agent_name="Agent One",
            task="do something",
            result="text output",
            ai_message=msg,
            metadata={},
            execution_time=1.0,
        )
        assert result.ai_message is msg
        assert result.ai_message.data == {"revenue": [100, 200, 300]}
        assert result.ai_message.code == "df.sum()"
        assert len(result.ai_message.artifacts) == 1

    def test_to_text_still_uses_result_not_ai_message(self):
        msg = _make_ai_message(output="rich output with data")
        result = AgentResult(
            agent_id="agent1",
            agent_name="Agent One",
            task="do something",
            result="simple text",
            ai_message=msg,
            metadata={},
            execution_time=1.0,
        )
        text = result.to_text()
        assert "simple text" in text
        assert "rich output with data" not in text

    def test_backward_compatible_without_ai_message(self):
        result = AgentResult(
            agent_id="agent1",
            agent_name="Agent One",
            task="do something",
            result="text output",
            metadata={"key": "value"},
            execution_time=1.5,
        )
        assert result.result == "text output"
        assert result.ai_message is None
        assert result.metadata == {"key": "value"}
