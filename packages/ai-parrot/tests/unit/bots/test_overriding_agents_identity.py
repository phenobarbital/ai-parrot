"""HOTFIX-otel-attribution-3 — agents overriding ask() still bind agent and tenant."""

from __future__ import annotations

import inspect
from typing import Any, AsyncIterator, Iterator

import pytest

from parrot.bots.base import BaseBot, with_call_identity
from parrot.bots.data import PandasAgent
from parrot.bots.database.agent import DatabaseAgent
from parrot.bots.voice import VoiceBot
from parrot.models.voice import LiveVoiceResponse, VoiceConfig
from parrot.observability.context import (
    current_agent_name,
    current_memory_key_id,
    current_session_id,
    current_tenant,
    current_user_id,
)


@pytest.mark.parametrize("agent_cls", [PandasAgent, DatabaseAgent])
def test_overriding_ask_is_wrapped_with_call_identity(agent_cls: type) -> None:
    """The override is the decorated wrapper, not the bare coroutine."""
    ask = agent_cls.__dict__["ask"]
    assert hasattr(ask, "__wrapped__")
    assert inspect.iscoroutinefunction(ask)


@pytest.mark.asyncio
async def test_decorator_binds_agent_and_tenant_on_overriding_ask() -> None:
    """A decorated override sees agent and tenant inside, and they reset after."""
    seen: dict[str, Any] = {}

    class _Probe(BaseBot):
        @with_call_identity
        async def ask(self, question: str, ctx: Any = None, **kwargs: Any) -> str:
            seen["agent"] = current_agent_name.get()
            seen["tenant"] = current_tenant.get()
            return question

    probe = object.__new__(_Probe)
    probe.name = "probe-agent"
    before = (current_agent_name.get(), current_tenant.get())
    assert await probe.ask("hi", tenant="t1") == "hi"
    assert seen == {"agent": "probe-agent", "tenant": "t1"}
    assert (current_agent_name.get(), current_tenant.get()) == before


# ── VoiceBot: behaviour of the async-generator entry points ─────────────

_VOICE_NAME = "voice-probe"
_IDENTITY_VARS = (current_agent_name, current_tenant, current_user_id, current_session_id, current_memory_key_id)
_OUTER = ("outer-agent", "outer-tenant", "outer-user", "outer-session", "outer-memkey")


class _IdentityRecordingClient:
    """Voice client double recording the bound identity at every step it runs.

    Each entry point records once before its first response and once after
    resuming from it, so a test can tell the identity stays bound across the
    generator's suspension points. ``fail`` raises before anything is yielded.
    """

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.seen: list[tuple[str | None, str | None]] = []

    async def __aenter__(self) -> "_IdentityRecordingClient":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    def _record(self) -> None:
        self.seen.append((current_agent_name.get(), current_tenant.get()))

    async def _responses(self) -> AsyncIterator[LiveVoiceResponse]:
        self._record()
        if self.fail:
            raise RuntimeError("provider down")
        yield LiveVoiceResponse(text="one", role="assistant", turn_id="turn-1", is_complete=False)
        self._record()
        yield LiveVoiceResponse(text="two", role="assistant", turn_id="turn-1", is_complete=True)

    async def stream_voice(self, audio_iterator: Any = None, **kwargs: Any) -> AsyncIterator[LiveVoiceResponse]:
        async for response in self._responses():
            yield response

    async def ask(self, question: str = "", **kwargs: Any) -> AsyncIterator[LiveVoiceResponse]:
        async for response in self._responses():
            yield response


def _snapshot() -> tuple[Any, ...]:
    """Every context variable a VoiceBot entry point binds, in ``_IDENTITY_VARS`` order."""
    return tuple(var.get() for var in _IDENTITY_VARS)


@pytest.fixture
def outer_identity() -> Iterator[tuple[Any, ...]]:
    """An enclosing call identity, so a reset must restore it rather than the defaults."""
    tokens = [var.set(value) for var, value in zip(_IDENTITY_VARS, _OUTER, strict=True)]
    yield _OUTER
    for var, token in reversed(list(zip(_IDENTITY_VARS, tokens, strict=True))):
        var.reset(token)


def _voice_call(method: str, client: _IdentityRecordingClient) -> AsyncIterator[LiveVoiceResponse]:
    """Start ``VoiceBot.<method>`` with tenant ``t1`` against ``client``."""
    bot = VoiceBot(name=_VOICE_NAME, voice_config=VoiceConfig())
    bot._llm = client  # type: ignore[assignment]
    first_arg: Any = b"audio" if method == "ask_stream" else "hello"
    return getattr(bot, method)(first_arg, user_id="u1", session_id="s1", tenant="t1")


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["ask", "ask_stream"])
async def test_voicebot_binds_identity_and_restores_after_full_drain(
    method: str, outer_identity: tuple[Any, ...]
) -> None:
    """The client sees the bot's agent and tenant at every step; the caller's identity is back after."""
    client = _IdentityRecordingClient()
    responses = [r async for r in _voice_call(method, client)]

    assert [r.text for r in responses] == ["one", "two"]
    assert client.seen == [(_VOICE_NAME, "t1"), (_VOICE_NAME, "t1")]
    assert _snapshot() == outer_identity


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["ask", "ask_stream"])
async def test_voicebot_restores_identity_on_early_aclose(method: str, outer_identity: tuple[Any, ...]) -> None:
    """A consumer that stops after the first response and closes the stream gets its identity back."""
    client = _IdentityRecordingClient()
    stream = _voice_call(method, client)

    first = await stream.__anext__()
    await stream.aclose()

    assert first.text == "one"
    assert client.seen == [(_VOICE_NAME, "t1")]
    assert _snapshot() == outer_identity


@pytest.mark.asyncio
async def test_voicebot_ask_restores_identity_when_client_raises(outer_identity: tuple[Any, ...]) -> None:
    """``ask`` propagates a client failure and still restores the caller's identity."""
    client = _IdentityRecordingClient(fail=True)

    with pytest.raises(RuntimeError, match="provider down"):
        async for _ in _voice_call("ask", client):
            pass

    assert client.seen == [(_VOICE_NAME, "t1")]
    assert _snapshot() == outer_identity


@pytest.mark.asyncio
async def test_voicebot_ask_stream_restores_identity_when_client_raises(outer_identity: tuple[Any, ...]) -> None:
    """``ask_stream`` turns a client failure into an error response and still restores the caller's identity."""
    client = _IdentityRecordingClient(fail=True)

    responses = [r async for r in _voice_call("ask_stream", client)]

    assert [r.metadata.get("error") for r in responses] == ["provider down"]
    assert client.seen == [(_VOICE_NAME, "t1")]
    assert _snapshot() == outer_identity
