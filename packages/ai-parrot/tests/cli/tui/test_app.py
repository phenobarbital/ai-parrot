"""Interaction tests for AgentWorkspaceApp (FEAT-573, spec §4 TUI rows)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, List
from unittest.mock import MagicMock

import pytest

pytest.importorskip("textual")

from prompt_toolkit.history import InMemoryHistory  # verified: repl.py:16

from parrot.cli.commands import SlashCommandDispatcher  # verified: commands.py:70
from parrot.cli.events import (
    TextDelta,
    ToolFinished,
    ToolStarted,
    TurnCancelled,
    TurnCompleted,
    TurnEventKind,
    TurnStarted,
)
from parrot.cli.repl import REPLConfig  # verified: repl.py:61
from parrot.cli.tui.app import AgentWorkspaceApp
from parrot.cli.tui.widgets import Composer, LogDrawer, StatusBar, ToolActivity, TranscriptView, TurnPanel


class _FakeRunner:
    """Scripted TurnRunner: yields the given events slowly; cancel() ends with TurnCancelled."""

    def __init__(self, script: List[Any], delay: float = 0.01) -> None:
        self.script, self.delay, self.history, self._active, self._cancelled = script, delay, [], False, False

    @property
    def is_active(self) -> bool:
        return self._active

    def cancel(self) -> bool:
        self._cancelled = True
        return self._active

    def reset_session(self) -> str:
        return "new-session"

    async def run_turn(self, query: str) -> AsyncIterator[Any]:
        self._active = True
        try:
            yield TurnStarted(kind=TurnEventKind.STARTED, turn_id="t", seq=0, query=query, streaming=True)
            for i, ev in enumerate(self.script, start=1):
                await asyncio.sleep(self.delay)
                if self._cancelled:
                    yield TurnCancelled(kind=TurnEventKind.CANCELLED, turn_id="t", seq=i, partial_text="partial")
                    return
                yield ev
        finally:
            self._active = False


def _app(runner: _FakeRunner) -> AgentWorkspaceApp:
    bot = MagicMock()
    bot.get_available_tools.return_value = []
    bot.get_tools_count.return_value = 0
    return AgentWorkspaceApp(
        bot=bot,
        config=REPLConfig(agent_name="a"),
        runner=runner,
        dispatcher=SlashCommandDispatcher(),
        history=InMemoryHistory(),
    )


def _deltas(*texts: str) -> List[Any]:
    evs = [TextDelta(kind=TurnEventKind.DELTA, turn_id="t", seq=i + 1, text=t) for i, t in enumerate(texts)]
    evs.append(
        TurnCompleted(
            kind=TurnEventKind.COMPLETED,
            turn_id="t",
            seq=len(evs) + 1,
            text="".join(texts),
            message=MagicMock(usage=None, tool_calls=[]),
        )
    )
    return evs


@pytest.mark.asyncio
async def test_submit_streams_and_follows():
    app = _app(_FakeRunner(_deltas("Hello", " world")))
    async with app.run_test() as pilot:
        await app.submit("hi")
        await pilot.pause(0.2)
        view = app.query_one("#transcript", TranscriptView)
        assert len(view.query(TurnPanel)) == 1 and view.following is True


@pytest.mark.asyncio
async def test_second_submit_rejected_while_active():
    """A second submission while a turn is active is rejected and the typed text is kept (AC4)."""
    app = _app(_FakeRunner(_deltas("Hello", " world", " again"), delay=0.05))
    async with app.run_test() as pilot:
        await app.submit("first request")
        await pilot.pause(0.02)
        assert app.runner.is_active is True

        await app.submit("second request")
        await pilot.pause(0.3)

        view = app.query_one("#transcript", TranscriptView)
        assert len(view.query(TurnPanel)) == 1
        composer = app.query_one("#composer", Composer)
        assert composer.text == "second request"


@pytest.mark.asyncio
async def test_ctrl_c_cancels_then_double_press_quits():
    """Ctrl+C cancels an active turn via ``runner.cancel()``; an idle double-press quits (AC18)."""
    app = _app(_FakeRunner(_deltas("Hello", " world", " again"), delay=0.05))
    async with app.run_test() as pilot:
        await app.submit("hi")
        await pilot.pause(0.02)
        assert app.runner.is_active is True

        await pilot.press("ctrl+c")
        await pilot.pause(0.3)
        assert app.runner.is_active is False
        assert app.runner._cancelled is True
        view = app.query_one("#transcript", TranscriptView)
        assert len(view.query(TurnPanel)) == 1  # cancellation renders into the existing panel, no new one

        # idle now: Ctrl+C once more just warns, a second press within 2s exits with code 0.
        await pilot.press("ctrl+c")
        await pilot.pause()
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert app.return_code == 0


@pytest.mark.asyncio
async def test_tool_rows_and_f2_toggle():
    """A ToolStarted/ToolFinished pair (same call_id) yields one tool row; F2 flips ``collapsed`` (AC6)."""
    script: List[Any] = [
        ToolStarted(kind=TurnEventKind.TOOL_STARTED, turn_id="t", seq=1, call_id="c1", tool_name="search"),
        ToolFinished(
            kind=TurnEventKind.TOOL_FINISHED,
            turn_id="t",
            seq=2,
            call_id="c1",
            tool_name="search",
            duration_ms=5.0,
            result_status="ok",
            result_size_bytes=3,
        ),
    ]
    script += _deltas("done")
    app = _app(_FakeRunner(script))
    async with app.run_test() as pilot:
        await app.submit("search something")
        await pilot.pause(0.2)
        panel = app.query_one("#transcript", TranscriptView).query_one(TurnPanel)
        assert len(panel._tools._rows) == 1
        assert panel._tools.collapsed is True

        await pilot.press("f2")
        await pilot.pause()
        assert panel._tools.collapsed is False


@pytest.mark.asyncio
async def test_slash_quit_exits_zero_and_logs_routed():
    """``/quit`` exits with code 0; log records land in the drawer, never the transcript (AC14/AC20)."""
    app = _app(_FakeRunner([]))
    async with app.run_test() as pilot:
        logging.getLogger("parrot.test.tui_app").warning("hello from app logs")
        await pilot.pause()
        drawer = app.query_one("#logs", LogDrawer)
        drawer_text = "".join(strip.text for strip in drawer.lines)
        assert "hello from app logs" in drawer_text
        assert len(app.query_one("#transcript", TranscriptView).query(".notice")) == 0

        await app.submit("/quit")
        await pilot.pause()
    assert app.return_code == 0


@pytest.mark.asyncio
async def test_resize_narrow_collapses_tools():
    """A narrow resize (< 60 cols) forces every tool panel collapsed; the composer stays mounted."""
    script: List[Any] = [
        ToolStarted(kind=TurnEventKind.TOOL_STARTED, turn_id="t", seq=1, call_id="c1", tool_name="search")
    ]
    script += _deltas("done")
    app = _app(_FakeRunner(script))
    async with app.run_test(size=(80, 24)) as pilot:
        await app.submit("search something")
        await pilot.pause(0.2)
        await pilot.press("f2")
        await pilot.pause()
        panel = app.query_one("#transcript", TranscriptView).query_one(TurnPanel)
        assert panel._tools.collapsed is False

        await pilot.resize_terminal(50, 20)
        await pilot.pause()
        assert all(tool_panel.collapsed for tool_panel in app.query(ToolActivity))
        assert app.query_one("#composer", Composer) is not None
