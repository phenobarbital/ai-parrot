from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.clients.factory import LLMFactory
from parrot.clients.zai import ZaiClient
from parrot.models import AIMessage, ZaiModel
from pydantic import BaseModel


class Answer(BaseModel):
    answer: str


def completion_response(content="Hello Z.ai", tool_calls=None, usage=None):
    message = SimpleNamespace(
        content=content,
        role="assistant",
        reasoning_content="reasoning",
        tool_calls=tool_calls,
    )
    choice = SimpleNamespace(message=message, finish_reason="stop")
    return SimpleNamespace(
        choices=[choice],
        usage=usage
        or SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            prompt_tokens_details=SimpleNamespace(cached_tokens=3),
            completion_tokens_details=SimpleNamespace(reasoning_tokens=2),
        ),
        model="glm-5.1",
        id="resp_1",
    )


def stream_chunk(content=None, reasoning=None, tool_calls=None, finish_reason=None, usage=None):
    delta = SimpleNamespace(
        content=content,
        reasoning_content=reasoning,
        tool_calls=tool_calls,
    )
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason, index=0)
    return SimpleNamespace(choices=[choice], usage=usage, model="glm-5.1")


@pytest.mark.asyncio
async def test_zai_ask_sends_thinking_and_structured_output():
    fake_sdk = MagicMock()
    fake_sdk.chat.completions.create.return_value = completion_response('{"answer": "42"}')

    client = ZaiClient(api_key="fake")
    client._ensure_client = AsyncMock(return_value=fake_sdk)

    response = await client.ask(
        "answer exactly",
        model=ZaiModel.GLM_5_1,
        structured_output=Answer,
        thinking=True,
    )

    assert isinstance(response, AIMessage)
    assert response.is_structured is True
    assert response.structured_output.answer == "42"
    assert response.metadata["reasoning_content"] == "reasoning"
    assert response.metadata["cached_tokens"] == 3

    call_kwargs = fake_sdk.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "glm-5.1"
    assert call_kwargs["thinking"] == {"type": "enabled"}
    assert call_kwargs["response_format"]["type"] == "json_schema"


@pytest.mark.asyncio
async def test_zai_ask_executes_current_tool_infrastructure():
    provider_tool_call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name="lookup", arguments='{"query": "zai"}'),
    )
    fake_sdk = MagicMock()
    fake_sdk.chat.completions.create.side_effect = [
        completion_response("", tool_calls=[provider_tool_call]),
        completion_response("tool complete", tool_calls=None),
    ]

    client = ZaiClient(api_key="fake", use_tools=True)
    client._ensure_client = AsyncMock(return_value=fake_sdk)
    client._execute_tool = AsyncMock(return_value={"ok": True})
    client.register_tool(
        name="lookup",
        description="Lookup a value.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        function=lambda query: {"query": query},
    )

    response = await client.ask("use lookup")

    assert response.response == "tool complete"
    assert response.tool_calls[0].name == "lookup"
    assert response.tool_calls[0].arguments == {"query": "zai"}
    assert response.tool_calls[0].result == {"ok": True}
    assert fake_sdk.chat.completions.create.call_args_list[0].kwargs["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_zai_ask_stream_supports_reasoning_tool_stream_and_final_message():
    tool_delta = SimpleNamespace(
        index=0,
        id="call_1",
        type="function",
        function=SimpleNamespace(name="lookup", arguments='{"query":"zai"}'),
    )
    final_usage = SimpleNamespace(
        prompt_tokens=4,
        completion_tokens=6,
        total_tokens=10,
        prompt_tokens_details=SimpleNamespace(cached_tokens=1),
        completion_tokens_details=None,
    )
    fake_sdk = MagicMock()
    fake_sdk.chat.completions.create.side_effect = [
        iter(
            [
                stream_chunk(reasoning="think ", tool_calls=[tool_delta]),
                stream_chunk(finish_reason="tool_calls"),
            ]
        ),
        iter(
            [
                stream_chunk(content="done", finish_reason="stop", usage=final_usage),
            ]
        ),
    ]

    client = ZaiClient(api_key="fake", use_tools=True)
    client._ensure_client = AsyncMock(return_value=fake_sdk)
    client._execute_tool = AsyncMock(return_value="tool result")
    client.register_tool(
        name="lookup",
        description="Lookup a value.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        function=lambda query: query,
    )

    chunks = []
    async for chunk in client.ask_stream("stream tool", thinking=True, stream_reasoning=True):
        chunks.append(chunk)

    assert chunks[0] == "think "
    assert chunks[1] == "done"
    assert isinstance(chunks[-1], AIMessage)
    assert chunks[-1].response == "done"
    assert chunks[-1].tool_calls[0].name == "lookup"
    first_call = fake_sdk.chat.completions.create.call_args_list[0].kwargs
    assert first_call["stream"] is True
    assert first_call["tool_stream"] is True


def test_zai_factory_and_models():
    client = LLMFactory.create("zai:glm-4.5-flash:free", api_key="fake")

    assert isinstance(client, ZaiClient)
    assert client.model == "glm-4.5-flash:free"
    assert ZaiModel.GLM_5_1.value == "glm-5.1"
    assert ZaiModel.GLM_4_7_FLASH_FREE.value.endswith(":free")
