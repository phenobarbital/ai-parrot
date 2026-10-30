"""FEAT-752 rev 0.3 TASK-4807 — opt-in trailing suggestions frame on the AgentTalk stream."""

from __future__ import annotations

import asyncio
import json
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

_AGENT_SRC = Path(__file__).resolve().parents[2] / "src" / "parrot" / "handlers" / "agent.py"
_SEP = b"\n\x00"


def _agent_module():
    return pytest.importorskip("parrot.handlers.agent")


def _message(suggestions=None):
    from parrot.models.basic import CompletionUsage
    from parrot.models.responses import AIMessage

    return AIMessage(
        input="hello",
        output="world",
        response="world",
        model="test-model",
        provider="test-provider",
        usage=CompletionUsage(prompt_tokens=1, completion_tokens=2),
        suggestions=suggestions or [],
    )


class _Recorder:
    """Fake chunked response recording headers and every write."""

    last: "_Recorder | None" = None

    def __init__(self, **kwargs) -> None:
        self.headers = kwargs["headers"]
        self.writes: list[bytes] = []
        self.eof = False
        _Recorder.last = self

    async def prepare(self, request) -> None:
        return None

    async def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        return None

    async def write_eof(self) -> None:
        self.eof = True

    @property
    def body(self) -> bytes:
        return b"".join(self.writes)


class _Bot:
    """Streaming bot: yields text, then an AIMessage carrying an optional deferred chip task."""

    def __init__(self, message, *, chips=None, delay=0.0, boom=False, timeout=4.0) -> None:
        self.calls: list[dict] = []
        self.message = message
        self._chips = chips
        self._delay = delay
        self._boom = boom
        self.suggestion_timeout_s = timeout
        self.task: "asyncio.Task | None" = None

    async def ask_stream(self, **kwargs):
        self.calls.append(kwargs)
        yield "hello"
        if kwargs.get("defer_suggestions"):

            async def attach():
                await asyncio.sleep(self._delay)
                if self._boom:
                    raise RuntimeError("chip llm down")
                self.message.suggestions = list(self._chips or [])
                return self.message

            self.task = asyncio.create_task(attach())
            self.message._suggestions_task = self.task
        elif self._chips:
            self.message.suggestions = list(self._chips)
        yield self.message


async def _run(monkeypatch, bot, *, trailer):
    agent_module = _agent_module()
    monkeypatch.setattr(agent_module.web, "StreamResponse", _Recorder)
    handler = SimpleNamespace(
        request=SimpleNamespace(app={}),
        logger=MagicMock(),
        _maybe_start_avatar_speaker=AsyncMock(return_value=None),
    )
    cls = agent_module.AgentTalk
    handler._write_suggestions_trailer = types.MethodType(cls._write_suggestions_trailer, handler)
    handler._cancel_suggestions_task = cls._cancel_suggestions_task
    await cls._handle_stream_response(
        handler,
        bot=bot,
        query="hello",
        session_id="s1",
        user_id="u1",
        search_type="similarity",
        return_sources=True,
        use_vector_context=True,
        use_conversation_history=True,
        output_mode=agent_module.OutputMode.DEFAULT,
        format_kwargs={},
        memory=None,
        llm=None,
        agent_name="agent-1",
        suggestions_trailer=trailer,
    )
    return _Recorder.last


def _chip(label="A"):
    from parrot.models import Suggestion

    return Suggestion(label=label, prompt=label.lower())


def _frames(resp: _Recorder) -> list[bytes]:
    return resp.body.split(_SEP)


async def test_trailer_off_is_v1_wire(monkeypatch):
    bot = _Bot(_message(), chips=[_chip()])
    resp = await _run(monkeypatch, bot, trailer=False)

    assert resp.headers["X-Parrot-Stream"] == "chunked-aimessage"
    assert bot.calls[0]["defer_suggestions"] is False
    frames = _frames(resp)
    assert len(frames) == 2  # text + envelope, no trailer
    envelope = json.loads(frames[1])
    assert envelope["suggestions"] == [
        {"label": "A", "prompt": "a", "output_mode": None, "kind": "followup", "source": "provider", "action": None}
    ]
    assert resp.eof


async def test_trailer_on_writes_second_frame(monkeypatch):
    bot = _Bot(_message(), chips=[_chip("A"), _chip("B")])
    resp = await _run(monkeypatch, bot, trailer=True)

    assert resp.headers["X-Parrot-Stream"] == "chunked-aimessage+suggestions"
    assert bot.calls[0]["defer_suggestions"] is True
    frames = _frames(resp)
    assert len(frames) == 3  # text, envelope, trailer
    assert frames[0] == b"hello"
    envelope = json.loads(frames[1])
    assert "suggestions" not in envelope
    trailer = json.loads(frames[2])
    assert set(trailer) == {"suggestions", "turn_id"}
    assert [c["label"] for c in trailer["suggestions"]] == ["A", "B"]
    assert resp.eof


async def test_trailer_skipped_on_empty(monkeypatch):
    bot = _Bot(_message(), chips=[])
    resp = await _run(monkeypatch, bot, trailer=True)
    assert len(_frames(resp)) == 2
    assert resp.eof


async def test_trailer_skipped_on_timeout_and_task_cancelled(monkeypatch):
    bot = _Bot(_message(), chips=[_chip()], delay=5.0, timeout=-0.99)  # wait_for budget = 0.01s
    resp = await _run(monkeypatch, bot, trailer=True)
    assert len(_frames(resp)) == 2
    assert resp.eof
    await asyncio.sleep(0)
    assert bot.task is not None and bot.task.cancelled()


async def test_trailer_skipped_when_chip_task_fails(monkeypatch):
    bot = _Bot(_message(), chips=[_chip()], boom=True)
    resp = await _run(monkeypatch, bot, trailer=True)
    assert len(_frames(resp)) == 2
    assert resp.eof


async def test_cancel_helper_cancels_running_task_only():
    cls = _agent_module().AgentTalk

    async def forever():
        await asyncio.sleep(10)

    running = asyncio.create_task(forever())
    done = asyncio.create_task(asyncio.sleep(0))
    await done

    cls._cancel_suggestions_task(SimpleNamespace(_suggestions_task=running))
    cls._cancel_suggestions_task(SimpleNamespace(_suggestions_task=done))  # no-op, no error
    cls._cancel_suggestions_task(SimpleNamespace())  # no attribute
    cls._cancel_suggestions_task(None)
    await asyncio.sleep(0)
    assert running.cancelled()


def test_flag_is_popped_and_forwarded_in_post():
    source = _AGENT_SRC.read_text(encoding="utf-8")
    assert 'suggestions_trailer: bool = bool(data.pop("suggestions_trailer", False))' in source
    assert source.index('data.pop("suggestions_trailer", False)') < source.index(
        "suggestions_trailer=suggestions_trailer,"
    )
    # only `defer_suggestions` reaches the bot, never the raw flag
    assert "suggestions_trailer=suggestions_trailer" in source
    assert "defer_suggestions=suggestions_trailer," in source
    stream_call = source.split("async for chunk in bot.ask_stream(", 1)[1].split("):", 1)[0]
    assert "suggestions_trailer=" not in stream_call


_PRE_FEAT_752_ENVELOPE_KEYS = {"input", "output", "metadata", "sources", "tool_calls"}


@pytest.mark.parametrize("trailer", [False, True])
async def test_chipless_stream_envelope_keeps_the_pre_feature_key_set(monkeypatch, trailer):
    """Golden check through the real handler: no chips means no `suggestions` key and no second frame."""
    bot = _Bot(_message(), chips=[])
    resp = await _run(monkeypatch, bot, trailer=trailer)

    frames = _frames(resp)
    assert len(frames) == 2  # text + envelope only
    envelope = json.loads(frames[1])
    assert set(envelope) == _PRE_FEAT_752_ENVELOPE_KEYS
    assert "suggestions" not in envelope["metadata"]
