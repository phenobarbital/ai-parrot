"""FEAT-707 — tenant binding in ask()/ask_stream() (TASK-4496)."""

from contextvars import ContextVar
from typing import ClassVar
from unittest.mock import MagicMock, patch

import pytest

from parrot.bots.basic import BasicBot
from parrot.bots.guardrails.base import (
    Guardrail,
    GuardrailAction,
    GuardrailContext,
    GuardrailResult,
    GuardrailStage,
)
from parrot.models import AIMessage, CompletionUsage
from parrot.utils.helpers import RequestContext

_tenant_var: ContextVar = ContextVar("test_tenant_var", default=None)
_ASK_KW = dict(use_conversation_history=False, use_vector_context=False, use_tools=False)


class _Recorder(Guardrail):
    """INPUT guardrail that records the tenant ContextVar seen mid-call."""

    name = "tenant_recorder"
    stages: ClassVar[set] = {GuardrailStage.INPUT}
    priority = 1
    on_error = "fail_open"

    def __init__(self, seen: list):
        super().__init__()
        self.seen = seen

    async def check(self, content, ctx: GuardrailContext):
        self.seen.append(_tenant_var.get())
        return GuardrailResult(action=GuardrailAction.PASS)


class _FakeAsyncClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def ask_stream(self, prompt, **kw):
        for part in ("a", "b", "c"):
            yield part


def _make_bot(with_hooks: bool, seen: list, calls: list, hook_calls: list):
    with patch("parrot.bots.guardrails.builtin.prompt_injection._get_shared_injection_detector") as shared:
        det = MagicMock()
        det.detect_injection.return_value = (False, 0.0)
        shared.return_value = det
        bot = BasicBot(name="TenantBot")
    bot._guardrail_pipelines[GuardrailStage.INPUT].add(_Recorder(seen))
    bot.get_client = MagicMock(return_value=_FakeAsyncClient())
    bot._llm = _FakeAsyncClient()

    async def _fake_execute(client, method, **kw):
        calls.append(kw)
        return AIMessage(
            input=kw.get("prompt", ""),
            output="ok",
            model="m",
            provider="p",
            usage=CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            session_id="s1",
        )

    bot.execute_llm_call = _fake_execute
    if with_hooks:

        def _enter(tenant, ctx):
            hook_calls.append((tenant, ctx))
            if tenant == "bad":
                raise ValueError("invalid tenant")
            return _tenant_var.set(tenant)

        bot._enter_skill_tenant = _enter
        bot._exit_skill_tenant = lambda token: _tenant_var.reset(token)
    return bot


@pytest.fixture
def state():
    return {"seen": [], "calls": [], "hooks": []}


@pytest.fixture
def bot(state):
    return _make_bot(True, state["seen"], state["calls"], state["hooks"])


@pytest.mark.asyncio
async def test_ask_binds_and_resets_tenant(bot, state):
    await bot.ask("hello", tenant="acme", **_ASK_KW)
    assert state["seen"] == ["acme"]
    assert _tenant_var.get() is None
    assert all("tenant" not in c for c in state["calls"])


@pytest.mark.asyncio
async def test_ask_passes_ctx_to_hook(bot, state):
    ctx = RequestContext(tenant="x")
    await bot.ask("hello", ctx=ctx, tenant=None, **_ASK_KW)
    assert state["hooks"] == [(None, ctx)]


@pytest.mark.asyncio
async def test_ask_reset_on_exception(bot, state):
    async def boom(*a, **k):
        raise RuntimeError("boom")

    bot._run_input_pipeline = boom
    with pytest.raises(RuntimeError):
        await bot.ask("hello", tenant="acme", **_ASK_KW)
    assert _tenant_var.get() is None


@pytest.mark.asyncio
async def test_ask_hook_value_error_propagates(bot, state):
    with pytest.raises(ValueError):
        await bot.ask("hello", tenant="bad", **_ASK_KW)
    assert _tenant_var.get() is None
    assert state["calls"] == []


@pytest.mark.asyncio
async def test_ask_stream_holds_tenant_across_iteration(bot, state):
    seen_in_loop = []
    async for _chunk in bot.ask_stream("hello", tenant="acme", **_ASK_KW):
        seen_in_loop.append(_tenant_var.get())
    assert state["seen"] == ["acme"]
    assert seen_in_loop and all(v == "acme" for v in seen_in_loop)
    assert _tenant_var.get() is None


@pytest.mark.asyncio
async def test_ask_stream_reset_on_aclose(bot, state):
    gen = bot.ask_stream("hello", tenant="acme", **_ASK_KW)
    await gen.__anext__()
    assert _tenant_var.get() == "acme"
    await gen.aclose()
    assert _tenant_var.get() is None


@pytest.mark.asyncio
async def test_non_mixin_bot_ignores_tenant_kwarg(state):
    plain = _make_bot(False, state["seen"], state["calls"], state["hooks"])
    result = await plain.ask("hello", tenant="acme", **_ASK_KW)
    assert isinstance(result, AIMessage)
    assert state["seen"] == [None]
    assert state["hooks"] == []
    assert all("tenant" not in c for c in state["calls"])
