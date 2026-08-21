"""Tool-loop + completion-funnel parity tests for FEAT-438 TASK-2297/2298.

Verifies the shared ``OpenAIBaseClient._run_tool_call_loop()`` reproduces
the semantics of the two inline loops it replaces
(``OpenAIClient.ask()``/``resume()``): lazy-tool re-preparation, fallback
metadata, usage accumulation, and final ``tool_calls`` assignment, plus the
two documented ``ask()`` vs ``resume()`` corner-case differences the shared
loop preserves via ``record_malformed_tool_calls``/``default_tool_name``.

Also verifies (TASK-2298) that ``ask()``/``ask_stream()``/``invoke()`` all
route through the single ``_chat_completion()`` funnel, that
``ask_stream()`` still yields str chunks then a final ``AIMessage``
(TASK-1175 contract), and that ``invoke()`` still returns an
``InvokeResult``.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from parrot.clients.gpt import OpenAIClient
from parrot.clients.openai_base import OpenAIBaseClient
from parrot.models import AIMessage
from parrot.models.responses import InvokeResult


def test_openai_client_extends_base():
    assert issubclass(OpenAIClient, OpenAIBaseClient)


def _make_message(content=None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def _make_tool_call(call_id, name, arguments):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _make_response(message, usage=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


class _LoopStub(OpenAIBaseClient):
    """Minimal concrete OpenAIBaseClient subclass to exercise the shared loop."""

    client_type = "stub"

    async def get_client(self):  # pragma: no cover - not exercised here
        return None

    async def ask_stream(self, *a, **kw):  # pragma: no cover
        raise NotImplementedError

    async def invoke(self, *a, **kw):  # pragma: no cover
        raise NotImplementedError


@pytest.mark.asyncio
async def test_tool_loop_executes_and_accumulates():
    """Two-round tool call: loop executes tools, accumulates usage, sets
    final AIMessage.tool_calls — identical to pre-refactor behavior."""
    client = _LoopStub(api_key="k", base_url="http://x/v1", model="m")
    client._execute_tool = AsyncMock(return_value="42")

    round1_tool_call = _make_tool_call("call_1", "calculator", '{"expression": "40+2"}')
    round1_message = _make_message(content=None, tool_calls=[round1_tool_call])
    round1_response = _make_response(round1_message, usage=SimpleNamespace(
        prompt_tokens=10, completion_tokens=5, total_tokens=15,
    ))

    final_message = _make_message(content="the answer is 42", tool_calls=None)
    final_response = _make_response(final_message, usage=SimpleNamespace(
        prompt_tokens=8, completion_tokens=4, total_tokens=12,
    ))

    call_completion = AsyncMock(return_value=final_response)

    messages = []
    result, response, all_tool_calls, accumulated_usage, round_number = await client._run_tool_call_loop(
        result=round1_message,
        response=round1_response,
        messages=messages,
        model_str="m",
        use_tools=True,
        args={},
        call_completion=call_completion,
        track_usage=True,
    )

    assert result is final_message
    assert response is final_response
    assert len(all_tool_calls) == 1
    assert all_tool_calls[0].name == "calculator"
    assert all_tool_calls[0].result == "42"
    assert round_number == 2
    # Accumulated usage sums both rounds.
    assert accumulated_usage.prompt_tokens == 18
    assert accumulated_usage.completion_tokens == 9
    call_completion.assert_awaited_once()


@pytest.mark.asyncio
async def test_malformed_tool_call_recorded_by_default_ask_semantics():
    """ask() semantics (record_malformed_tool_calls=True, default_tool_name=None):
    a malformed tool-call is still recorded in all_tool_calls."""
    client = _LoopStub(api_key="k", base_url="http://x/v1", model="m")

    bad_tool_call = _make_tool_call("call_1", "calculator", "{not valid json")
    round1_message = _make_message(content=None, tool_calls=[bad_tool_call])
    round1_response = _make_response(round1_message)

    final_message = _make_message(content="done", tool_calls=None)
    final_response = _make_response(final_message)
    call_completion = AsyncMock(return_value=final_response)

    _result, _response, all_tool_calls, _usage, _rounds = await client._run_tool_call_loop(
        result=round1_message,
        response=round1_response,
        messages=[],
        model_str="m",
        use_tools=True,
        args={},
        call_completion=call_completion,
        record_malformed_tool_calls=True,
    )

    assert len(all_tool_calls) == 1
    assert "_error" in all_tool_calls[0].arguments


@pytest.mark.asyncio
async def test_malformed_tool_call_dropped_with_resume_semantics():
    """resume() semantics (record_malformed_tool_calls=False): a malformed
    tool-call is NOT recorded — preserves the pre-existing (subtly
    inconsistent) behavior of the original duplicated loop."""
    client = _LoopStub(api_key="k", base_url="http://x/v1", model="m")

    bad_tool_call = _make_tool_call("call_1", "calculator", "{not valid json")
    round1_message = _make_message(content=None, tool_calls=[bad_tool_call])
    round1_response = _make_response(round1_message)

    final_message = _make_message(content="done", tool_calls=None)
    final_response = _make_response(final_message)
    call_completion = AsyncMock(return_value=final_response)

    _result, _response, all_tool_calls, _usage, _rounds = await client._run_tool_call_loop(
        result=round1_message,
        response=round1_response,
        messages=[],
        model_str="m",
        use_tools=True,
        args={},
        call_completion=call_completion,
        record_malformed_tool_calls=False,
    )

    assert all_tool_calls == []


@pytest.mark.asyncio
async def test_lazy_loading_reprepares_tools():
    """lazy_loading=True re-prepares tools with filter_names after a
    search_tools call surfaces new tool names."""
    client = _LoopStub(api_key="k", base_url="http://x/v1", model="m", use_tools=True)
    client._execute_tool = AsyncMock(return_value="found: weather_tool")
    client._check_new_tools = lambda name, content: ["weather_tool"]
    client._prepare_tools = lambda filter_names=None: [{"filtered_for": filter_names}]

    search_call = _make_tool_call("call_1", "search_tools", '{"query": "weather"}')
    round1_message = _make_message(content=None, tool_calls=[search_call])
    round1_response = _make_response(round1_message)

    final_message = _make_message(content="done", tool_calls=None)
    final_response = _make_response(final_message)
    call_completion = AsyncMock(return_value=final_response)

    args = {}
    active_tool_names = {"search_tools"}
    await client._run_tool_call_loop(
        result=round1_message,
        response=round1_response,
        messages=[],
        model_str="m",
        use_tools=True,
        args=args,
        call_completion=call_completion,
        lazy_loading=True,
        active_tool_names=active_tool_names,
    )

    assert len(args["tools"]) == 1
    assert set(args["tools"][0]["filtered_for"]) == {"search_tools", "weather_tool"}


class _FunnelSpy(OpenAIBaseClient):
    """Records every ``_chat_completion`` call; returns a canned response."""

    client_type = "funnel-spy"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.calls = []

    async def get_client(self):
        return SimpleNamespace()

    async def _chat_completion(self, model, messages, use_tools=False, stream=False, **kwargs):
        self.calls.append(
            {"model": model, "messages": messages, "use_tools": use_tools, "stream": stream, "kwargs": kwargs}
        )
        if stream:

            async def _gen():
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="hello"))],
                    usage=None,
                )
                yield SimpleNamespace(
                    choices=[],
                    usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                )

            return _gen()
        message = _make_message(content="hi", tool_calls=None)
        return _make_response(message, usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5))


async def _noop_conversation_context(*_a, **_kw):
    return [], None, None


async def _noop_update_conversation_memory(*_a, **_kw):
    return None


def _make_funnel_spy(**kwargs):
    client = _FunnelSpy(api_key="k", base_url="http://x/v1", model="m", **kwargs)
    client._prepare_conversation_context = _noop_conversation_context
    client._update_conversation_memory = _noop_update_conversation_memory
    return client


@pytest.mark.asyncio
async def test_ask_routes_via_funnel():
    client = _make_funnel_spy()
    result = await client.ask("hello")
    assert len(client.calls) == 1
    assert client.calls[0]["model"] == "m"
    assert isinstance(result, AIMessage)


@pytest.mark.asyncio
async def test_ask_stream_routes_via_funnel():
    client = _make_funnel_spy()
    _ = [item async for item in client.ask_stream("hello")]
    assert len(client.calls) == 1
    assert client.calls[0]["stream"] is True


@pytest.mark.asyncio
async def test_ask_stream_final_yield_is_aimessage():
    """TASK-1175 contract: ask_stream yields str chunks then a final AIMessage."""
    client = _make_funnel_spy()
    chunks = [item async for item in client.ask_stream("hello")]
    assert chunks[0] == "hello"
    assert isinstance(chunks[-1], AIMessage)


@pytest.mark.asyncio
async def test_invoke_routes_via_funnel():
    client = _make_funnel_spy()
    await client._ensure_client()
    result = await client.invoke("hello")
    assert len(client.calls) == 1
    assert client.calls[0]["use_tools"] is True
    assert isinstance(result, InvokeResult)
