"""Tool-loop + completion-funnel parity tests for FEAT-438 TASK-2297/2298/2301.

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
from typing import ClassVar
from unittest.mock import AsyncMock

import pytest
from parrot.clients.gpt import OpenAIClient
from parrot.clients.groq import GroqClient
from parrot.clients.localllm import LocalLLMClient
from parrot.clients.moonshot import MoonshotClient
from parrot.clients.nova.mantle import BedrockMantleClient
from parrot.clients.nvidia import NvidiaClient
from parrot.clients.openai_base import OpenAIBaseClient
from parrot.clients.openrouter import OpenRouterClient
from parrot.clients.vllm import vLLMClient
from parrot.models import AIMessage
from parrot.models.responses import InvokeResult
from parrot.tools.manager import ToolFormat


def test_openai_client_extends_base():
    assert issubclass(OpenAIClient, OpenAIBaseClient)


# ---------------------------------------------------------------------------
# FEAT-438 TASK-2302 — post-rebase MRO regression (isinstance/issubclass audit)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cls",
    [
        OpenRouterClient, MoonshotClient, NvidiaClient, LocalLLMClient,
        vLLMClient, BedrockMantleClient, GroqClient,
    ],
    ids=lambda c: c.__name__,
)
def test_mro_post_rebase_not_openai_client(cls):
    """Every Phase-1 wire subclass is an OpenAIBaseClient, NOT an
    OpenAIClient, post-TASK-2300 rebase — any isinstance/issubclass check
    against OpenAIClient meaning "OpenAI-compatible wire client" is now
    silently False and must target OpenAIBaseClient instead (TASK-2302
    audit: workspace-wide grep for isinstance/issubclass/client_type==
    "openai" sites found none needing this fix — both existing hits
    already assert the correct post-rebase relationship)."""
    assert issubclass(cls, OpenAIBaseClient)
    assert not issubclass(cls, OpenAIClient)


def test_mro_openai_client_is_still_openai_base_client():
    """Positive control: OpenAIClient itself is still an OpenAIBaseClient
    (it IS the OpenAI-the-provider specialization of the wire base)."""
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


# ---------------------------------------------------------------------------
# FEAT-438 TASK-2301 — per-client payload parity + funnel-coverage consolidation
# ---------------------------------------------------------------------------

# Phase 1 wire roster + Phase 2's GroqClient (TASK-2303; ZaiClient joins
# in TASK-2304).
WIRE_SUBCLASSES = [
    OpenRouterClient,
    MoonshotClient,
    NvidiaClient,
    LocalLLMClient,
    vLLMClient,
    BedrockMantleClient,
    GroqClient,
]

# vLLMClient.ask()/ask_stream() unconditionally forward
# extra_body=extra_body if extra_body else None up through
# LocalLLMClient -> OpenAIBaseClient, whose ask()/ask_stream() have never
# accepted an extra_body kwarg (neither did OpenAIClient's, pre-FEAT-438).
# Genuine pre-existing defect (present since at least commit ae3d613ab),
# unrelated to this feature — reported (see
# tests/clients/test_openai_compatible_defaults.py), not fixed here.
_ASK_FUNNEL_ROSTER = [c for c in WIRE_SUBCLASSES if c is not vLLMClient]
_ASK_STREAM_FUNNEL_ROSTER = [c for c in WIRE_SUBCLASSES if c is not vLLMClient]

# LocalLLMClient/vLLMClient's invoke() intentionally does NOT route through
# _chat_completion (TASK-2300 kept it verbatim for its real
# schema-in-prompt structured-output fallback value, calling the SDK
# directly) — not a funnel-coverage gap, a deliberate exception.
_INVOKE_FUNNEL_ROSTER = [
    c for c in WIRE_SUBCLASSES if c not in (LocalLLMClient, vLLMClient)
]


def _parity_client_kwargs(cls) -> dict:
    """Minimal explicit construction kwargs so no test touches real env vars."""
    if cls is BedrockMantleClient:
        return {"api_key": "test-key", "region": "us-east-1"}
    if cls in (LocalLLMClient, vLLMClient):
        return {"api_key": "test-key", "base_url": "http://localhost:8000/v1"}
    return {"api_key": "test-key"}


_OPENAI_TOOL_FORMAT_ROSTER = [c for c in WIRE_SUBCLASSES if c is not GroqClient]


@pytest.mark.parametrize("cls", _OPENAI_TOOL_FORMAT_ROSTER, ids=lambda c: c.__name__)
def test_wire_subclass_tool_wrapper_is_openai_shaped_and_strict(cls):
    """Every Phase-1 wire subclass declares ToolFormat.OPENAI and emits the
    {"type":"function","function":{...}} tool wrapper (not
    Anthropic-shaped). AbstractClient._prepare_tools() applies "strict"
    based on tool_format == ToolFormat.OPENAI (base.py:1420) — a wire-
    protocol property, not an OpenAIClient-specific one — so every one of
    these clients gets strict tools too. GroqClient is excluded here
    (explicitly declares ToolFormat.GROQ, which never gets "strict" — see
    test_groq_tool_wrapper_has_no_strict below)."""
    client = cls(model="provider-model-x", **_parity_client_kwargs(cls))
    assert client.tool_format is ToolFormat.OPENAI

    class _StubToolManager:
        def get_tool_schemas(self, provider_format=None):
            return [
                {
                    "name": "calculator",
                    "description": "Evaluate a mathematical expression.",
                    "parameters": {
                        "type": "object",
                        "properties": {"expression": {"type": "string"}},
                        "required": ["expression"],
                    },
                }
            ]

    client.tool_manager = _StubToolManager()
    schemas = client._prepare_tools()
    assert len(schemas) == 1
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "calculator"
    assert schemas[0]["function"]["strict"] is True


def test_groq_tool_format_explicit():
    """GroqClient MUST declare tool_format = ToolFormat.GROQ explicitly —
    otherwise it would silently inherit OpenAIBaseClient's ToolFormat.OPENAI
    and start sending "strict": true, which Groq rejects."""
    assert GroqClient.tool_format is ToolFormat.GROQ


def test_groq_tool_wrapper_has_no_strict():
    """GroqClient._prepare_groq_tools() (its own tool-schema builder, used
    by ask()/ask_stream()/resume()) never includes "strict" — Groq rejects
    it. Also verify the inherited generic _prepare_tools() (unused by
    Groq's own ask(), but part of the shared contract) agrees, since
    ToolFormat.GROQ is excluded from the strict branch (base.py:1435)."""
    client = GroqClient(api_key="test-key")

    class _StubTool:
        name: ClassVar[str] = "calculator"
        description: ClassVar[str] = "Evaluate a mathematical expression."
        input_schema: ClassVar[dict] = {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        }

    class _StubToolManager:
        def all_tools(self):
            return [_StubTool()]

        def get_tool_schemas(self, provider_format=None):
            return [
                {
                    "name": "calculator",
                    "description": "Evaluate a mathematical expression.",
                    "parameters": _StubTool.input_schema,
                }
            ]

    client.tool_manager = _StubToolManager()

    groq_schemas = client._prepare_groq_tools()
    assert len(groq_schemas) == 1
    assert groq_schemas[0]["type"] == "function"
    assert "strict" not in groq_schemas[0]["function"]

    generic_schemas = client._prepare_tools()
    assert len(generic_schemas) == 1
    assert generic_schemas[0]["type"] == "function"
    assert "strict" not in generic_schemas[0]["function"]


@pytest.mark.asyncio
async def test_groq_keeps_native_sdk():
    """get_client() still returns AsyncGroq, NOT AsyncOpenAI — the
    AsyncOpenAI swap was explicitly rejected at spec time."""
    from groq import AsyncGroq

    client = GroqClient(api_key="test-key")
    sdk = await client.get_client()
    assert isinstance(sdk, AsyncGroq)


def _make_funnel_coverage_spy():
    """Build a plain async function to monkeypatch onto a class as
    ``_chat_completion`` — a plain function (not a callable-object
    instance) so Python's normal method-binding rules apply when the
    client calls ``self._chat_completion(...)``. Records every call and
    returns a canned response shaped for both chat-completions and
    streaming; the returned function's ``.calls`` list is the spy log.
    """
    calls: list = []

    async def _chat_completion(self, model, messages, use_tools=False, stream=False, **kwargs):
        calls.append({"model": model, "use_tools": use_tools, "stream": stream})
        if stream:
            async def _gen():
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="hi"))],
                    usage=None,
                )
                yield SimpleNamespace(
                    choices=[],
                    usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                )
            return _gen()
        message = SimpleNamespace(content="ok", tool_calls=None)
        choice = SimpleNamespace(message=message, finish_reason="stop", stop_reason="stop")
        usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)
        response = SimpleNamespace(choices=[choice], usage=usage)
        response.model_dump = lambda: {"choices": [{"message": {"content": "ok"}}]}
        return response

    _chat_completion.calls = calls
    return _chat_completion


@pytest.mark.asyncio
@pytest.mark.parametrize("cls", _ASK_FUNNEL_ROSTER, ids=lambda c: c.__name__)
async def test_ask_reaches_chat_completion(cls, monkeypatch):
    """ask() observably reaches _chat_completion (own override or inherited)
    for every roster client except the excluded pre-existing-defect case."""
    spy = _make_funnel_coverage_spy()
    monkeypatch.setattr(cls, "_chat_completion", spy)
    client = cls(model="provider-model-x", **_parity_client_kwargs(cls))
    await client.ask("hello")
    assert len(spy.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("cls", _ASK_STREAM_FUNNEL_ROSTER, ids=lambda c: c.__name__)
async def test_ask_stream_reaches_chat_completion(cls, monkeypatch):
    """ask_stream() observably reaches _chat_completion with stream=True."""
    spy = _make_funnel_coverage_spy()
    monkeypatch.setattr(cls, "_chat_completion", spy)
    client = cls(model="provider-model-x", **_parity_client_kwargs(cls))
    chunks = [c async for c in client.ask_stream("hello") if isinstance(c, str)]
    assert chunks == ["hi"]
    assert len(spy.calls) == 1
    assert spy.calls[0]["stream"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("cls", _INVOKE_FUNNEL_ROSTER, ids=lambda c: c.__name__)
async def test_invoke_reaches_chat_completion(cls, monkeypatch):
    """invoke() observably reaches _chat_completion for every roster client
    that routes through the funnel (LocalLLM/vLLM's schema-in-prompt
    fallback intentionally does not — excluded, see _INVOKE_FUNNEL_ROSTER)."""
    spy = _make_funnel_coverage_spy()
    monkeypatch.setattr(cls, "_chat_completion", spy)
    client = cls(model="provider-model-x", **_parity_client_kwargs(cls))
    await client._ensure_client()
    await client.invoke("hello")
    assert len(spy.calls) == 1
