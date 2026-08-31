"""Unit tests for per-round ClientRoundEvent emission from LLMCodeDispatcher
(FEAT-405, TASK-2089, Module 6).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from parrot.clients.base import AbstractClient
from parrot.core.events.lifecycle.events.client import (
    AfterClientCallEvent,
    ClientRoundEvent,
)
from parrot.flows.dev_loop import (
    DevelopmentOutput,
    LLMCodeDispatcher,
    LLMCodeDispatchProfile,
    ResearchOutput,
)

# ---------------------------------------------------------------------------
# Fakes — OpenAI-shaped response objects (mirrors test_llm_code_dispatcher.py)
# ---------------------------------------------------------------------------


class _Function:
    def __init__(self, name: str, arguments: dict[str, Any]) -> None:
        self.name = name
        self.arguments = json.dumps(arguments)


class _ToolCall:
    def __init__(self, call_id: str, name: str, arguments: dict[str, Any]) -> None:
        self.id = call_id
        self.function = _Function(name, arguments)


class _Message:
    def __init__(self, *, content: str = "", tool_calls: Sequence[_ToolCall] = ()) -> None:
        self.content = content
        self.tool_calls = list(tool_calls)


class _Choice:
    def __init__(self, message: _Message) -> None:
        self.message = message


class _Usage:
    def __init__(self, prompt_tokens: int, completion_tokens: int, total_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens

    def model_dump(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


class _Response:
    def __init__(self, message: _Message, usage: _Usage | None = None) -> None:
        self.choices = [_Choice(message)]
        self.usage = usage


# ---------------------------------------------------------------------------
# A real AbstractClient subclass (genuine _emit_* trio, no I/O) — mirrors
# test_client_lifecycle.py's _StubClient, extended with _chat_completion so
# LLMCodeDispatcher's turn loop can drive it directly.
# ---------------------------------------------------------------------------


class _EmittingFakeClient(AbstractClient):
    client_name = "fake-emitting"

    def __init__(self, responses: Sequence[_Response]) -> None:
        super().__init__(debug=False)
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def ask(self, prompt: str, model: str = "stub-model", **kw):  # type: ignore[override]
        raise NotImplementedError("stub")

    async def ask_stream(self, prompt: str, **kw):  # type: ignore[override]
        raise NotImplementedError("stub")
        yield  # pragma: no cover - makes this an async generator

    async def get_client(self):
        return None

    async def _ensure_client(self):
        pass

    async def invoke(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError("stub")

    async def resume(self, *args, **kwargs):  # type: ignore[override]
        raise NotImplementedError("stub")

    async def _chat_completion(self, **kwargs: Any) -> _Response:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("fake client exhausted")
        return self.responses.pop(0)


class _PlainClient:
    """A client with NO _emit_* methods at all — must not break dispatch."""

    client = object()
    model = "plain-model"

    def __init__(self, responses: Sequence[_Response]) -> None:
        self.responses = list(responses)

    async def _chat_completion(self, **kwargs: Any) -> _Response:
        if not self.responses:
            raise AssertionError("fake client exhausted")
        return self.responses.pop(0)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_worktree_base(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "parrot.flows.dev_loop.dispatchers.llm.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )
    return tmp_path


@pytest.fixture
def brief(_patch_worktree_base) -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-fix",
        worktree_path=str(_patch_worktree_base),
        log_excerpts=[],
    )


def _dispatcher(monkeypatch, client: Any) -> LLMCodeDispatcher:
    def _client_factory(*args: Any, **kwargs: Any) -> Any:
        return client

    disp = LLMCodeDispatcher(
        max_concurrent=2,
        redis_url="redis://localhost:6379/0",
        stream_ttl_seconds=300,
        client_factory=_client_factory,
    )
    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")

    async def _ensure_redis():
        return fake_redis

    monkeypatch.setattr(disp, "_ensure_redis", _ensure_redis)
    return disp


def _final_output_call(call_id: str = "call_final") -> _ToolCall:
    return _ToolCall(
        call_id,
        "final_output",
        {"files_changed": [], "commit_shas": [], "summary": "done"},
    )


async def _run_dispatch(dispatcher, brief, cwd, *, max_turns=4) -> DevelopmentOutput:
    return await dispatcher.dispatch(
        brief=brief,
        profile=LLMCodeDispatchProfile(llm="fake:fake-model", max_turns=max_turns),
        output_model=DevelopmentOutput,
        run_id="r1",
        node_id="development",
        cwd=cwd,
    )


class _Collector:
    """Subscribes to ClientRoundEvent on a client's own registry."""

    def __init__(self, client: AbstractClient) -> None:
        self.events: list[ClientRoundEvent] = []
        client.events.subscribe(ClientRoundEvent, self._capture)

    async def _capture(self, event: ClientRoundEvent) -> None:
        self.events.append(event)


class _AfterCallCollector:
    """Subscribes to AfterClientCallEvent on a client's own registry."""

    def __init__(self, client: AbstractClient) -> None:
        self.events: list[AfterClientCallEvent] = []
        client.events.subscribe(AfterClientCallEvent, self._capture)

    async def _capture(self, event: AfterClientCallEvent) -> None:
        self.events.append(event)


async def _drain() -> None:
    """Let emit_nowait's fire-and-forget scheduled tasks run."""
    for _ in range(3):
        await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRoundEvents:
    async def test_one_event_per_turn(self, monkeypatch, brief, _patch_worktree_base):
        client = _EmittingFakeClient([_Response(_Message(content="turn 1", tool_calls=[_final_output_call()]))])
        collector = _Collector(client)
        dispatcher = _dispatcher(monkeypatch, client)
        await _run_dispatch(dispatcher, brief, str(_patch_worktree_base))
        await _drain()

        assert [e.round_number for e in collector.events] == [1]

    async def test_three_turns_emit_three_events_in_order(self, monkeypatch, brief, _patch_worktree_base):
        client = _EmittingFakeClient(
            [
                _Response(_Message(content="t1", tool_calls=[_ToolCall("c1", "read_file", {"path": "x"})])),
                _Response(_Message(content="t2", tool_calls=[_ToolCall("c2", "read_file", {"path": "x"})])),
                _Response(_Message(content="t3", tool_calls=[_final_output_call("c3")])),
            ]
        )
        collector = _Collector(client)
        dispatcher = _dispatcher(monkeypatch, client)
        (_patch_worktree_base / "x").write_text("hi", encoding="utf-8")
        await _run_dispatch(dispatcher, brief, str(_patch_worktree_base))
        await _drain()

        assert [e.round_number for e in collector.events] == [1, 2, 3]

    async def test_events_carry_per_round_usage_not_totals(self, monkeypatch, brief, _patch_worktree_base):
        """Each event is one round — the dispatcher must not accumulate."""
        client = _EmittingFakeClient(
            [
                _Response(
                    _Message(content="t1", tool_calls=[_ToolCall("c1", "read_file", {"path": "x"})]),
                    usage=_Usage(10, 5, 15),
                ),
                _Response(
                    _Message(content="t2", tool_calls=[_final_output_call("c2")]),
                    usage=_Usage(10, 5, 15),
                ),
            ]
        )
        collector = _Collector(client)
        dispatcher = _dispatcher(monkeypatch, client)
        (_patch_worktree_base / "x").write_text("hi", encoding="utf-8")
        await _run_dispatch(dispatcher, brief, str(_patch_worktree_base))
        await _drain()

        assert len(collector.events) == 2
        assert all(e.input_tokens == 10 for e in collector.events)
        assert all(e.output_tokens == 5 for e in collector.events)

    async def test_missing_usage_is_tolerated(self, monkeypatch, brief, _patch_worktree_base):
        client = _EmittingFakeClient([_Response(_Message(content="t1", tool_calls=[_final_output_call()]), usage=None)])
        collector = _Collector(client)
        dispatcher = _dispatcher(monkeypatch, client)
        await _run_dispatch(dispatcher, brief, str(_patch_worktree_base))
        await _drain()

        assert collector.events
        assert collector.events[0].input_tokens is None

    async def test_client_without_emitters_does_not_break(self, monkeypatch, brief, _patch_worktree_base):
        """A test double lacking _emit_* must still dispatch successfully."""
        client = _PlainClient([_Response(_Message(content="t1", tool_calls=[_final_output_call()]))])
        dispatcher = _dispatcher(monkeypatch, client)
        result = await _run_dispatch(dispatcher, brief, str(_patch_worktree_base))
        assert result is not None
        assert result.summary == "done"

    async def test_no_events_when_no_subscribers(self, monkeypatch, brief, _patch_worktree_base):
        """has_subscribers short-circuit — no collector attached at all."""
        client = _EmittingFakeClient([_Response(_Message(content="t1", tool_calls=[_final_output_call()]))])
        dispatcher = _dispatcher(monkeypatch, client)
        result = await _run_dispatch(dispatcher, brief, str(_patch_worktree_base))
        await _drain()
        assert result is not None
        assert client.events.has_subscribers(ClientRoundEvent) is False

    async def test_non_nova_backend_also_emits(self, monkeypatch, brief, _patch_worktree_base):
        """[R8]: coverage is backend-independent — exercised via LLMCodeDispatcher
        directly (the shared base every nvidia/zai/moonshot/grok/nova dispatcher
        subclasses), so this proves coverage without depending on any one backend.
        """
        client = _EmittingFakeClient([_Response(_Message(content="t1", tool_calls=[_final_output_call()]))])
        collector = _Collector(client)
        dispatcher = _dispatcher(monkeypatch, client)
        await _run_dispatch(dispatcher, brief, str(_patch_worktree_base))
        await _drain()
        assert collector.events

    async def test_emit_after_call_awaited_exactly_once(self, monkeypatch, brief, _patch_worktree_base):
        client = _EmittingFakeClient([_Response(_Message(content="t1", tool_calls=[_final_output_call()]))])
        calls: list[Any] = []
        original = client._emit_after_call

        async def _spy(*args, **kwargs):
            calls.append((args, kwargs))
            return await original(*args, **kwargs)

        monkeypatch.setattr(client, "_emit_after_call", _spy)
        dispatcher = _dispatcher(monkeypatch, client)
        await _run_dispatch(dispatcher, brief, str(_patch_worktree_base))

        assert len(calls) == 1

    async def test_emit_after_call_fires_even_on_error(self, monkeypatch, brief, _patch_worktree_base):
        """_emit_after_call must still fire once when the turn loop itself
        raises (a genuine error inside ``_dispatch_loop``'s try/finally,
        as opposed to the pre-loop cwd guard in ``dispatch()``)."""
        client = _EmittingFakeClient([])  # exhausted immediately
        calls: list[Any] = []
        original = client._emit_after_call

        async def _spy(*args, **kwargs):
            calls.append((args, kwargs))
            return await original(*args, **kwargs)

        monkeypatch.setattr(client, "_emit_after_call", _spy)
        dispatcher = _dispatcher(monkeypatch, client)

        from parrot.flows.dev_loop import DispatchExecutionError

        with pytest.raises(DispatchExecutionError):
            await _run_dispatch(dispatcher, brief, str(_patch_worktree_base))
        assert len(calls) == 1


class TestNoAccumulation:
    def test_source_contains_no_summing(self):
        """Guard rail: the dispatcher must not re-implement FEAT-397's
        client-layer accumulation.
        """
        src = Path("packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py").read_text()
        assert "total_usage" not in src
        assert "_accumulated_usage" not in src


class TestAfterCallTokens:
    """FEAT-479 Module 3: the awaited AfterClientCallEvent must carry the
    per-call accumulated tokens, not None (spec §1 Finding 4).
    """

    async def test_dispatcher_after_call_carries_accumulated_tokens(self, monkeypatch, brief, _patch_worktree_base):
        """Regression guard for FEAT-479 Finding 4: _safe_emit_after_call
        dropped the token counts entirely, so the one AWAITED (exactly
        -delivered) event always reported None."""
        client = _EmittingFakeClient(
            [
                _Response(
                    _Message(content="t1", tool_calls=[_ToolCall("c1", "read_file", {"path": "x"})]),
                    usage=_Usage(1000, 500, 1500),
                ),
                _Response(
                    _Message(content="t2", tool_calls=[_final_output_call("c2")]),
                    usage=_Usage(2000, 700, 2700),
                ),
            ]
        )
        after_collector = _AfterCallCollector(client)
        dispatcher = _dispatcher(monkeypatch, client)
        (_patch_worktree_base / "x").write_text("hi", encoding="utf-8")
        await _run_dispatch(dispatcher, brief, str(_patch_worktree_base))

        assert len(after_collector.events) == 1
        assert after_collector.events[0].input_tokens == 3000  # summed, not 2000
        assert after_collector.events[0].output_tokens == 1200

    async def test_after_call_tokens_none_when_unreported(self, monkeypatch, brief, _patch_worktree_base):
        """No round reported usage -> None, never a fabricated 0."""
        client = _EmittingFakeClient([_Response(_Message(content="t1", tool_calls=[_final_output_call()]), usage=None)])
        after_collector = _AfterCallCollector(client)
        dispatcher = _dispatcher(monkeypatch, client)
        await _run_dispatch(dispatcher, brief, str(_patch_worktree_base))

        assert len(after_collector.events) == 1
        assert after_collector.events[0].input_tokens is None
        assert after_collector.events[0].output_tokens is None

    async def test_after_call_emitted_with_partial_tokens_on_failure(self, monkeypatch, brief, _patch_worktree_base):
        """A loop that raises (max_turns exhaustion) still reports the
        tokens burned before the failure."""
        client = _EmittingFakeClient(
            [
                _Response(
                    _Message(content="t1", tool_calls=[_ToolCall("c1", "read_file", {"path": "x"})]),
                    usage=_Usage(1000, 500, 1500),
                ),
            ]
        )
        after_collector = _AfterCallCollector(client)
        dispatcher = _dispatcher(monkeypatch, client)
        (_patch_worktree_base / "x").write_text("hi", encoding="utf-8")

        from parrot.flows.dev_loop import DispatchExecutionError

        with pytest.raises(DispatchExecutionError):
            await _run_dispatch(dispatcher, brief, str(_patch_worktree_base), max_turns=1)

        assert len(after_collector.events) == 1
        assert after_collector.events[0].input_tokens == 1000
        assert after_collector.events[0].output_tokens == 500

    async def test_round_events_still_one_per_round(self, monkeypatch, brief, _patch_worktree_base):
        """The per-call accumulation must not regress TASK-2089: round
        events remain one-per-round, carrying that round's own usage."""
        client = _EmittingFakeClient(
            [
                _Response(
                    _Message(content="t1", tool_calls=[_ToolCall("c1", "read_file", {"path": "x"})]),
                    usage=_Usage(1000, 500, 1500),
                ),
                _Response(
                    _Message(content="t2", tool_calls=[_final_output_call("c2")]),
                    usage=_Usage(2000, 700, 2700),
                ),
            ]
        )
        round_collector = _Collector(client)
        dispatcher = _dispatcher(monkeypatch, client)
        (_patch_worktree_base / "x").write_text("hi", encoding="utf-8")
        await _run_dispatch(dispatcher, brief, str(_patch_worktree_base))
        await _drain()

        assert [e.input_tokens for e in round_collector.events] == [1000, 2000]
        assert [e.output_tokens for e in round_collector.events] == [500, 700]
