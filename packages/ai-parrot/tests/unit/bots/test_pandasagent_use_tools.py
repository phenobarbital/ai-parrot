"""PandasAgent.ask() honours ``use_tools`` instead of pinning it to True.

A data agent asked to write prose from figures already in the prompt must be
able to switch its tool loop off per call: offering ~70 function declarations
on such a prompt made Gemini answer with MALFORMED_FUNCTION_CALL on every
retry. The flag is forwarded to the client; the shared ToolManager is never
mutated.
"""

from typing import Any, AsyncIterator, Dict, List, Optional, Union

import pytest

from parrot.bots.data import PandasAgent
from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage


class _RecordingClient:
    """Minimal async client that records the kwargs of every ask() call."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def __aenter__(self) -> "_RecordingClient":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def close(self) -> None:
        return None

    async def ask(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        history: Optional[list] = None,
        use_tools: Optional[bool] = None,
        structured_output: Any = None,
        max_tokens: Optional[int] = None,
        max_iterations: Optional[int] = None,
        stop_tools: Optional[set] = None,
        **kwargs: Any,
    ) -> AIMessage:
        self.calls.append(
            {
                "use_tools": use_tools,
                "max_iterations": max_iterations,
                "stop_tools": stop_tools,
                "system_prompt": system_prompt,
            }
        )
        return self._message(prompt)

    async def ask_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        use_tools: Optional[bool] = None,
        **kwargs: Any,
    ) -> AsyncIterator[Union[str, AIMessage]]:
        self.calls.append({"use_tools": use_tools, "system_prompt": system_prompt, "stream": True})
        yield "ok"
        yield self._message(prompt)

    @staticmethod
    def _message(prompt: str) -> AIMessage:
        return AIMessage(
            input=prompt,
            output="ok",
            response="ok",
            model="fake",
            provider="fake",
            usage=CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )


@pytest.fixture
def agent_and_client() -> tuple:
    agent = PandasAgent(name="use-tools-probe", llm="google:gemini-2.5-flash")
    client = _RecordingClient()
    agent._llm = client  # type: ignore[assignment]
    return agent, client


@pytest.mark.asyncio
async def test_use_tools_false_reaches_client(agent_and_client: tuple) -> None:
    agent, client = agent_and_client
    await agent.ask("hola", use_tools=False, return_structured=False, use_conversation_history=False)
    call = client.calls[-1]
    assert call["use_tools"] is False
    # Tool-loop knobs are not forwarded on a tool-less call.
    assert call["max_iterations"] is None
    assert call["stop_tools"] is None


@pytest.mark.asyncio
async def test_use_tools_defaults_to_true(agent_and_client: tuple) -> None:
    agent, client = agent_and_client
    await agent.ask("hola", return_structured=False, use_conversation_history=False)
    call = client.calls[-1]
    assert call["use_tools"] is True
    assert call["max_iterations"] is not None
    assert call["stop_tools"] == {"to_json"}


@pytest.mark.asyncio
async def test_use_tools_false_leaves_shared_tool_manager_intact(agent_and_client: tuple) -> None:
    agent, _ = agent_and_client
    before = sorted(agent.tool_manager.list_tools())
    await agent.ask("hola", use_tools=False, return_structured=False, use_conversation_history=False)
    assert sorted(agent.tool_manager.list_tools()) == before


# ── System prompt without tools ────────────────────────────────

_TOOL_MARKERS = ("python_repl_pandas", "list_datasets", "fetch_dataset", "get_metadata", "<data_instructions>")


@pytest.mark.asyncio
async def test_toolless_ask_sends_toolless_prompt(agent_and_client: tuple) -> None:
    agent, client = agent_and_client
    await agent.ask("hola", use_tools=False, return_structured=False, use_conversation_history=False)
    prompt = client.calls[-1]["system_prompt"]
    assert "No tools are available for this request" in prompt
    for marker in _TOOL_MARKERS:
        assert marker not in prompt, marker


@pytest.mark.asyncio
async def test_default_ask_keeps_data_instructions(agent_and_client: tuple) -> None:
    agent, client = agent_and_client
    await agent.ask("hola", return_structured=False, use_conversation_history=False)
    prompt = client.calls[-1]["system_prompt"]
    assert "<data_instructions>" in prompt
    assert "No tools are available for this request" not in prompt


def test_toolless_builder_is_a_clone(agent_and_client: tuple) -> None:
    agent, _ = agent_and_client
    shared = agent._prompt_builder
    before = sorted(shared.layer_names)
    toolless = agent._toolless_prompt_builder()
    assert toolless is not shared
    assert sorted(shared.layer_names) == before
    names = set(toolless.layer_names)
    assert "toolless_data_grounding" in names
    assert names.isdisjoint({"tools", "available_skills", "dataframe_context", "strict_grounding", "data_instructions"})


# ── ask_stream() / conversation() follow the same contract ─────


async def _drain(stream: AsyncIterator[Any]) -> None:
    async for _ in stream:
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("use_tools", [False, True])
async def test_ask_stream_honours_use_tools(agent_and_client: tuple, use_tools: bool) -> None:
    agent, client = agent_and_client
    await _drain(agent.ask_stream("hola", use_tools=use_tools, use_conversation_history=False))
    call = client.calls[-1]
    assert call["stream"] is True
    assert call["use_tools"] is use_tools
    assert ("No tools are available for this request" in call["system_prompt"]) is not use_tools


@pytest.mark.asyncio
async def test_conversation_explicit_use_tools_overrides_mode(agent_and_client: tuple) -> None:
    agent, client = agent_and_client
    await agent.conversation("hola", mode="agentic", use_tools=False, use_conversation_history=False)
    call = client.calls[-1]
    assert call["use_tools"] is False
    assert "No tools are available for this request" in call["system_prompt"]


@pytest.mark.asyncio
async def test_conversation_without_use_tools_keeps_mode(agent_and_client: tuple) -> None:
    agent, client = agent_and_client
    await agent.conversation("hola", mode="agentic", use_conversation_history=False)
    call = client.calls[-1]
    assert call["use_tools"] is True
    assert "No tools are available for this request" not in call["system_prompt"]
