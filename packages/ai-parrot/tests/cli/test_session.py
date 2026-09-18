"""Unit tests for parrot.cli.session.TurnRunner (FEAT-573 TASK-3404, spec §4)."""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from typing import Any, List

import pytest

from parrot.cli.events import (
    TurnCancelled,
    TurnCompleted,
    TurnEventKind,
    TurnFailed,  # provided by TASK-3403
    ToolFinished,
    ToolStarted,
)
from parrot.cli.session import TurnInProgressError, TurnRunner
from parrot.core.events.lifecycle import scope  # verified: lifecycle/__init__.py:22
from parrot.models.outputs import OutputMode  # verified: repl.py:24
from parrot.tools.abstract import AbstractTool, ToolResult  # verified: tests/unit/tools/test_tool_lifecycle.py:16


class _OkTool(AbstractTool):
    """Emits Before/After lifecycle events when executed (pattern: tests/unit/tools/test_tool_lifecycle.py:19)."""

    async def _execute(self, **kwargs) -> ToolResult:
        return ToolResult(status="success", result="ok")


def _config(**over: Any) -> SimpleNamespace:
    base = dict(agent_name="t", streaming=True, session_id="s-1", user_id="u", permission_context=None)
    base.update(over)
    return SimpleNamespace(**base)


class _FakeBot:
    def __init__(
        self, deltas: List[str], final: Any = None, tool: AbstractTool | None = None, fail_after: int | None = None
    ):
        self.deltas, self.final, self.tool, self.fail_after = deltas, final, tool, fail_after
        self.calls: List[dict] = []
        self.closed = False

    async def ask_stream(self, question: str, **kwargs):
        self.calls.append(kwargs)
        try:
            for i, d in enumerate(self.deltas):
                if self.fail_after is not None and i == self.fail_after:
                    raise RuntimeError("boom")
                if self.tool is not None and i == 1:
                    await self.tool.execute()  # emits inside the caller's task → inside turn_scope
                yield d
                await asyncio.sleep(0)
            if self.final is not None:
                yield self.final
        finally:
            self.closed = True

    async def ask(self, question: str, **kwargs):
        self.calls.append(kwargs)
        return self.final


class _SlowBot:
    """A backend whose stream never completes on its own — used to exercise cancellation."""

    def __init__(self) -> None:
        self.calls: List[dict] = []
        self.closed = False

    async def ask_stream(self, question: str, **kwargs):
        self.calls.append(kwargs)
        try:
            yield "a"
            await asyncio.Event().wait()
            yield "never"  # pragma: no cover — unreachable, Event is never set
        finally:
            self.closed = True

    async def ask(self, question: str, **kwargs):  # pragma: no cover — not used by these tests
        raise AssertionError("ask() should not be called in streaming tests")


@pytest.fixture
def _runner_lifecycle_scope():
    """Local equivalent of the shared ``lifecycle_scope`` conftest fixture (TASK-3416):

    renamed here to avoid shadowing conftest.py's fixture of the same name for every
    test in this module (pytest resolves the closest definition first).
    """
    with scope() as reg:
        yield reg


async def _collect(runner: TurnRunner, query: str):
    return [e async for e in runner.run_turn(query)]


@pytest.mark.asyncio
async def test_turn_event_seq_monotonic_and_terminal_once(_runner_lifecycle_scope, tmp_path, monkeypatch):
    monkeypatch.setenv("PARROT_HOME", str(tmp_path))
    final = SimpleNamespace(output="abc", response="abc", tool_calls=[], usage=None)
    runner = TurnRunner(_FakeBot(["a", "b", "c"], final), _config())
    events = await _collect(runner, "hi")
    kinds = [e.kind for e in events]
    assert kinds == [
        TurnEventKind.STARTED,
        TurnEventKind.DELTA,
        TurnEventKind.DELTA,
        TurnEventKind.DELTA,
        TurnEventKind.COMPLETED,
    ]
    assert [e.seq for e in events] == [0, 1, 2, 3, 4]
    assert isinstance(events[-1], TurnCompleted)
    assert len(runner.history) == 1
    assert runner.history[0].query == "hi"


@pytest.mark.asyncio
async def test_runner_live_tool_events_scoped(_runner_lifecycle_scope, tmp_path, monkeypatch):
    monkeypatch.setenv("PARROT_HOME", str(tmp_path))
    runner = TurnRunner(_FakeBot(["a", "b"], None, tool=_OkTool()), _config())
    events = await _collect(runner, "hi")

    started = [e for e in events if isinstance(e, ToolStarted)]
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert len(started) == 1
    assert len(finished) == 1
    assert started[0].call_id == finished[0].call_id

    completed_index = next(i for i, e in enumerate(events) if isinstance(e, TurnCompleted))
    assert events.index(started[0]) < completed_index
    assert events.index(finished[0]) < completed_index

    # A tool executed OUTSIDE any run_turn (no TURN_SCOPE set) must not leak Tool* events in.
    outside_tool = _OkTool()
    await outside_tool.execute()
    await asyncio.sleep(0)
    other_runner = TurnRunner(_FakeBot(["x"], None), _config())
    other_events = await _collect(other_runner, "hi2")
    assert not any(isinstance(e, (ToolStarted, ToolFinished)) for e in other_events)


@pytest.mark.asyncio
async def test_runner_batch_mode_uses_ask(_runner_lifecycle_scope, tmp_path, monkeypatch):
    monkeypatch.setenv("PARROT_HOME", str(tmp_path))
    final = SimpleNamespace(output="done", response="done", tool_calls=[], usage=None)
    bot = _FakeBot([], final)
    runner = TurnRunner(bot, _config(streaming=False, user_id=None))
    events = await _collect(runner, "hi")
    assert bot.calls == [{"session_id": "s-1", "output_mode": OutputMode.TERMINAL, "permission_context": None}]
    assert isinstance(events[-1], TurnCompleted)


@pytest.mark.asyncio
async def test_runner_cancel_yields_cancelled_and_closes_stream(_runner_lifecycle_scope, tmp_path, monkeypatch):
    monkeypatch.setenv("PARROT_HOME", str(tmp_path))
    bot = _SlowBot()
    hook_calls: List[Any] = []

    async def _hook(ctx: Any, turn: Any) -> None:
        hook_calls.append(turn)

    runner = TurnRunner(bot, _config())
    runner.add_post_turn_hook(_hook)
    events: List[Any] = []

    async def _consume() -> None:
        async for event in runner.run_turn("hi"):
            events.append(event)

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert runner.cancel() is True
    await task

    assert isinstance(events[-1], TurnCancelled)
    assert events[-1].partial_text == "a"
    assert bot.closed is True
    assert runner.history == []
    assert hook_calls == []


@pytest.mark.asyncio
async def test_runner_failure_preserves_partial(_runner_lifecycle_scope, tmp_path, monkeypatch):
    monkeypatch.setenv("PARROT_HOME", str(tmp_path))
    bot = _FakeBot(["a", "b", "c"], None, fail_after=1)
    runner = TurnRunner(bot, _config())
    events = await _collect(runner, "hi")
    assert isinstance(events[-1], TurnFailed)
    assert events[-1].partial_text == "a"
    assert events[-1].error_type == "RuntimeError"
    assert events[-1].error_message == "boom"
    assert runner.history == []


@pytest.mark.asyncio
async def test_runner_rejects_second_turn(_runner_lifecycle_scope, tmp_path, monkeypatch):
    monkeypatch.setenv("PARROT_HOME", str(tmp_path))
    bot = _SlowBot()
    runner = TurnRunner(bot, _config())

    async def _consume() -> None:
        async for _ in runner.run_turn("hi"):
            pass

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert runner.is_active is True

    with pytest.raises(TurnInProgressError):
        async for _ in runner.run_turn("again"):
            pass

    runner.cancel()
    await task


@pytest.mark.asyncio
async def test_runner_load_history_maps_memory_turns():
    inv = SimpleNamespace(tool_name="search", input={"q": "x"}, output="result", error=None)
    mem_turn = SimpleNamespace(
        user_message="hi",
        assistant_response="hello",
        tool_invocations=[inv],
        timestamp=datetime(2024, 1, 1),
        error=None,
    )
    history = SimpleNamespace(turns=[mem_turn])

    class _ResumeBot:
        async def get_conversation_history(self, user_id: str, session_id: str):
            assert user_id == "u"
            assert session_id == "s-2"
            return history

    runner = TurnRunner(_ResumeBot(), _config())
    turns = await runner.load_history("s-2")

    assert len(turns) == 1
    assert turns[0].query == "hi"
    assert turns[0].response.output == "hello"
    assert turns[0].response.tool_calls[0].name == "search"
    assert turns[0].response.tool_calls[0].arguments == {"q": "x"}
    assert turns[0].response.tool_calls[0].result == "result"
    assert runner.config.session_id == "s-2"
    assert runner.history == turns


@pytest.mark.asyncio
async def test_runner_post_turn_hook_after_completed_only(_runner_lifecycle_scope, tmp_path, monkeypatch):
    monkeypatch.setenv("PARROT_HOME", str(tmp_path))
    calls: List[Any] = []

    async def _hook(ctx: Any, turn: Any) -> None:
        calls.append((ctx, turn))

    final = SimpleNamespace(output="ok", response="ok", tool_calls=[], usage=None)
    runner = TurnRunner(_FakeBot(["a"], final), _config())
    runner.add_post_turn_hook(_hook)
    await _collect(runner, "hi")
    assert len(calls) == 1
    assert calls[0][0] is runner
    assert calls[0][1].query == "hi"

    # A FAILED turn must never run the hook.
    fail_runner = TurnRunner(_FakeBot(["a"], None, fail_after=0), _config())
    fail_runner.add_post_turn_hook(_hook)
    await _collect(fail_runner, "hi2")
    assert len(calls) == 1

    # A CANCELLED turn must never run the hook.
    cancel_runner = TurnRunner(_SlowBot(), _config())
    cancel_runner.add_post_turn_hook(_hook)

    async def _consume() -> None:
        async for _ in cancel_runner.run_turn("hi3"):
            pass

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    cancel_runner.cancel()
    await task
    assert len(calls) == 1
