"""Tests for AgentTool capturing AIMessage in execution_memory."""
import sys
import importlib.util
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# The conftest installs module stubs via sys.modules.setdefault(), which means
# any module already present in sys.modules keeps the real implementation.
# We force-load the real parrot modules before conftest stubs can shadow them.
# ---------------------------------------------------------------------------

_SRC = Path(__file__).resolve().parents[1] / "src"


def _force_real_module(dotted_name: str) -> object:
    """Load the real module from source, bypassing any conftest stub."""
    sys.modules.pop(dotted_name, None)
    parts = dotted_name.split(".")
    rel_path = Path(*parts).with_suffix(".py")
    spec = importlib.util.spec_from_file_location(dotted_name, _SRC / rel_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[dotted_name] = mod
    spec.loader.exec_module(mod)
    return mod


# Force real parrot.tools.agent — conftest stubs it with a _AgentTool that has no _execute
sys.modules.pop("parrot.tools.agent", None)
import parrot.tools.agent as _real_agent_mod  # noqa: E402

AgentTool = _real_agent_mod.AgentTool

# The real AIMessage / AgentResponse / CompletionUsage / AgentResult are already
# in sys.modules as the real things (they loaded transitively with tools.agent above).
from parrot.models.responses import AIMessage, AgentResponse  # noqa: E402
from parrot.models.basic import CompletionUsage  # noqa: E402
from parrot.models.crew import AgentResult  # noqa: E402


def _make_ai_message(**overrides) -> AIMessage:
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


def _make_mock_agent(name: str = "TestAgent", response=None):
    agent = AsyncMock()
    agent.name = name
    agent.role = "test role"
    agent.goal = "test goal"
    agent.capabilities = None
    if response is not None:
        agent.conversation = AsyncMock(return_value=response)
    return agent


def _make_execution_memory():
    """Create a minimal ExecutionMemory-like object for testing."""
    memory = MagicMock()
    memory.results = {}

    def add_result(result, vectorize=True):
        memory.results[result.agent_id] = result

    memory.add_result.side_effect = add_result
    return memory


class TestAgentToolAIMessageCapture:

    @pytest.mark.asyncio
    async def test_captures_ai_message_from_ask(self):
        msg = _make_ai_message(
            data={"revenue": [100, 200]},
            artifacts=[{"type": "sql", "content": "SELECT *"}],
        )
        agent = _make_mock_agent(response=msg)
        memory = _make_execution_memory()
        tool = AgentTool(agent=agent, execution_memory=memory)

        result = await tool._execute(question="What is revenue?")

        assert isinstance(result, str)
        stored = memory.results.get("TestAgent")
        assert stored is not None
        assert stored.ai_message is msg
        assert stored.ai_message.data == {"revenue": [100, 200]}

    @pytest.mark.asyncio
    async def test_captures_ai_message_from_agent_response(self):
        inner_msg = _make_ai_message(data={"profit": 42})
        agent_response = MagicMock(spec=AgentResponse)
        agent_response.content = "profit is 42"
        agent_response.output = "profit is 42"
        agent_response.response = inner_msg
        agent = _make_mock_agent(response=agent_response)
        memory = _make_execution_memory()
        tool = AgentTool(agent=agent, execution_memory=memory)

        await tool._execute(question="What is profit?")

        stored = memory.results["TestAgent"]
        assert stored.ai_message is inner_msg
        assert stored.ai_message.data == {"profit": 42}

    @pytest.mark.asyncio
    async def test_ai_message_is_none_for_string_response(self):
        agent = _make_mock_agent(response="plain text response")
        memory = _make_execution_memory()
        tool = AgentTool(agent=agent, execution_memory=memory)

        await tool._execute(question="Hello")

        stored = memory.results["TestAgent"]
        assert stored.ai_message is None
        assert stored.result == "plain text response"

    @pytest.mark.asyncio
    async def test_still_returns_string_to_caller(self):
        msg = _make_ai_message(
            output="text for LLM",
            data={"big": "payload"},
        )
        agent = _make_mock_agent(response=msg)
        memory = _make_execution_memory()
        tool = AgentTool(agent=agent, execution_memory=memory)

        result = await tool._execute(question="test")

        assert isinstance(result, str)
        assert "payload" not in result

    @pytest.mark.asyncio
    async def test_no_execution_memory_no_error(self):
        msg = _make_ai_message(data={"x": 1})
        agent = _make_mock_agent(response=msg)
        tool = AgentTool(agent=agent, execution_memory=None)

        result = await tool._execute(question="test")

        assert isinstance(result, str)
